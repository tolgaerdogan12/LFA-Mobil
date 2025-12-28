# Dosya Adı: lfa_motoru.py
# Sürüm: V15.1 (SyntaxError Fix - Girintiler Düzeltildi)

import cv2
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import find_peaks
import os
import time
import sqlite3
import json
import glob
from datetime import datetime
from fpdf import FPDF

# Scipy kontrolü
try:
    from scipy.optimize import curve_fit
    SCIPY_OK = True
except ImportError:
    SCIPY_OK = False

# --- AYARLAR ---
class Config:
    CONFIG_FILE = "config.json"
    BASE_OUTPUT_DIR = "analiz_sonuclari"
    DB_NAME = "lfa_veritabani.db"
    STD_WIDTH = 600
    STD_HEIGHT = 1200
    ROI_TEST_STRIP = [280, 440, 30, 200]
    PEAK_HEIGHT = 5       
    PEAK_PROMINENCE = 3   
    PEAK_DISTANCE = 20    
    AUC_WINDOW_RADIUS = 4 
    LINE_LOCATIONS = {"C": {"pos": 22, "color": "green"}, "T": {"pos": 108, "color": "red"}}
    POS_TOLERANCE = 15 

    @classmethod
    def load_config(cls):
        if os.path.exists(cls.CONFIG_FILE):
            try:
                with open(cls.CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                    if "LINE_LOCATIONS" in data: cls.LINE_LOCATIONS = data["LINE_LOCATIONS"]
                    if "POS_TOLERANCE" in data: cls.POS_TOLERANCE = data["POS_TOLERANCE"]
                    if "ROI_TEST_STRIP" in data: cls.ROI_TEST_STRIP = data["ROI_TEST_STRIP"]
            except: pass

    @classmethod
    def save_config(cls):
        data = {"LINE_LOCATIONS": cls.LINE_LOCATIONS, "POS_TOLERANCE": cls.POS_TOLERANCE, "ROI_TEST_STRIP": cls.ROI_TEST_STRIP}
        try:
            with open(cls.CONFIG_FILE, 'w') as f: json.dump(data, f, indent=4)
            return True
        except: return False

Config.load_config()

# --- VERİTABANI ---
class DatabaseManager:
    def __init__(self, db_name): 
        self.db_name = db_name
        self.init_db()
        
    def init_db(self):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS analizler (id INTEGER PRIMARY KEY AUTOINCREMENT, calisma_adi TEXT, hasta_id TEXT, dosya_adi TEXT, kaynak TEXT, matris TEXT, konsantrasyon REAL, notlar TEXT, tarih TEXT, c_auc REAL, t_auc REAL, ratio REAL, sonuc_yolu TEXT, grafik_yolu TEXT)''')
        conn.commit()
        conn.close()
    
    def kaydet(self, calisma_adi, hasta_id, dosya_adi, kaynak, matris, konsantrasyon, notlar, c_auc, t_auc, ratio, sonuc_yolu, grafik_yolu):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        tarih = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try: 
            r = float(ratio)
            k = float(konsantrasyon)
        except: 
            r = 0.0
            k = 0.0
        
        cursor.execute('''INSERT INTO analizler (calisma_adi, hasta_id, dosya_adi, kaynak, matris, konsantrasyon, notlar, tarih, c_auc, t_auc, ratio, sonuc_yolu, grafik_yolu) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''', (calisma_adi, hasta_id, dosya_adi, kaynak, matris, k, notlar, tarih, c_auc, t_auc, r, sonuc_yolu, grafik_yolu))
        conn.commit()
        conn.close()

    def sonuc_guncelle(self, dosya_adi, c_auc, t_auc, ratio, grafik_yolu):
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        try: 
            r = float(ratio)
        except: 
            r = 0.0
        cursor.execute('''UPDATE analizler SET c_auc=?, t_auc=?, ratio=?, grafik_yolu=? WHERE dosya_adi=?''', (c_auc, t_auc, r, grafik_yolu, dosya_adi))
        conn.commit()
        conn.close()

    def calisma_verilerini_getir(self, calisma_adi):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT * FROM analizler WHERE calisma_adi = ?", (calisma_adi,))
        res = c.fetchall()
        conn.close()
        return res
        
    def calisma_listesi_getir(self):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT DISTINCT calisma_adi FROM analizler ORDER BY id DESC")
        res = [r[0] for r in c.fetchall()]
        conn.close()
        return res
        
    def istatistik_verisi_getir(self, calisma_adi):
        conn = sqlite3.connect(self.db_name)
        c = conn.cursor()
        c.execute("SELECT kaynak, matris, konsantrasyon, c_auc, t_auc, ratio FROM analizler WHERE calisma_adi = ?", (calisma_adi,))
        res = c.fetchall()
        conn.close()
        return res

# --- PRO İSTATİSTİK MOTORU ---
class IstatistikMotoru:
    @staticmethod
    def model_linear(x, m, b): 
        return m * x + b
    
    @staticmethod
    def model_log_linear(x, m, b): 
        return m * np.log10(x) + b
    
    @staticmethod
    def model_4pl(x, a, b, c, d):
        x = np.asarray(x, dtype=float)
        return d + (a - d) / (1.0 + np.power(x / c, b))

    @staticmethod
    def r2_hesapla(y_true, y_pred):
        ss_res = np.sum((y_true - y_pred) ** 2)
        ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
        return 1 - (ss_res / ss_tot) if ss_tot != 0 else 0

    @staticmethod
    def en_iyi_modeli_bul(x, y):
        best_model = {"name": "Yetersiz Veri", "r2": -999, "params": None, "y_pred": None, "eq": ""}
        if len(x) < 3: return best_model

        # 1. Lineer Model
        try:
            m, b = np.polyfit(x, y, 1)
            y_pred = m * x + b
            r2 = IstatistikMotoru.r2_hesapla(y, y_pred)
            if r2 > best_model["r2"]:
                best_model = {"name": "Linear", "r2": r2, "params": (m, b), "y_pred": y_pred, "eq": f"y = {m:.4f}x + {b:.4f}"}
        except: pass

        # 2. Log-Lineer
        if np.all(x > 0):
            try:
                m, b = np.polyfit(np.log10(x), y, 1)
                y_pred = m * np.log10(x) + b
                r2 = IstatistikMotoru.r2_hesapla(y, y_pred)
                if r2 > best_model["r2"]:
                    best_model = {"name": "Log-Linear", "r2": r2, "params": (m, b), "y_pred": y_pred, "eq": f"y = {m:.4f}*log(x) + {b:.4f}"}
            except: pass

        # 3. 4PL
        if SCIPY_OK and np.all(x > 0) and len(x) >= 4:
            try:
                a0, d0 = float(np.max(y)), float(np.min(y))
                c0, b0 = float(np.median(x)), 1.0
                p0 = [a0, b0, c0, d0]
                bounds = ([-np.inf, -20, 1e-9, -np.inf], [np.inf, 20, np.inf, np.inf])
                popt, _ = curve_fit(IstatistikMotoru.model_4pl, x, y, p0=p0, bounds=bounds, maxfev=10000)
                y_pred = IstatistikMotoru.model_4pl(x, *popt)
                r2 = IstatistikMotoru.r2_hesapla(y, y_pred)
                if r2 > best_model["r2"]:
                    best_model = {"name": "4PL", "r2": r2, "params": popt, "y_pred": y_pred, "eq": f"4PL (R2={r2:.4f})"}
            except: pass
            
        return best_model

    @staticmethod
    def validasyon_analizi(veriler, gruplama_tipi="kaynak"):
        grup_idx = 0 if gruplama_tipi == "kaynak" else 1
        gruplar = {}
        for row in veriler:
            etiket = str(row[grup_idx]) if row[grup_idx] else "Belirsiz"
            val = row[5]
            if etiket not in gruplar: gruplar[etiket] = []
            gruplar[etiket].append(val)
            
        sonuclar, labels, plot_data = [], [], []
        for etiket, degerler in gruplar.items():
            if not degerler: continue
            arr = np.array(degerler)
            mean = np.mean(arr)
            std = np.std(arr)
            cv = (std / mean * 100) if mean != 0 else 0
            sonuclar.append({"grup": etiket, "n": len(arr), "ortalama": mean, "cv": cv})
            plot_data.append(degerler)
            labels.append(f"{etiket}\n(CV:{cv:.1f}%)")
        return sonuclar, labels, plot_data

    @staticmethod
    def kalibrasyon_egrisi(veriler):
        x_raw, y_raw = [], []
        for row in veriler:
            try:
                k = float(row[2])
                r = float(row[5])
                x_raw.append(k)
                y_raw.append(r)
            except: pass
            
        if len(x_raw) < 2: return None, None, None, {"eq": "Yetersiz Veri", "r2": 0, "name": "None"}
        
        x = np.array(x_raw)
        y = np.array(y_raw)
        idx = np.argsort(x)
        x = x[idx]
        y = y[idx]
        
        best = IstatistikMotoru.en_iyi_modeli_bul(x, y)
        
        x_smooth = np.linspace(min(x), max(x), 100)
        y_smooth = None
        
        if best["name"] == "Linear":
            m, b = best["params"]
            y_smooth = m * x_smooth + b
        elif best["name"] == "Log-Linear":
            m, b = best["params"]
            x_min_log = max(min(x), 1e-9)
            x_smooth = np.linspace(x_min_log, max(x), 100)
            y_smooth = m * np.log10(x_smooth) + b
        elif best["name"] == "4PL":
            popt = best["params"]
            y_smooth = IstatistikMotoru.model_4pl(x_smooth, *popt)
            
        return x, y, (x_smooth, y_smooth), best

# --- PDF ---
class PDFRapor(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'LFA LABORATUVAR ANALIZ RAPORU', 0, 0, 'L')
        self.line(10, 20, 200, 20)
        self.ln(15)
    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Sayfa {self.page_no()}', 0, 0, 'C')
    def add_patient_page(self, data):
        self.add_page()
        self.set_font('Arial', 'B', 10)
        self.set_fill_color(230, 230, 250)
        self.cell(0, 8, f"ORNEK ID: {data.get('hid', '-')}", 1, 1, 'L', 1)
        self.ln(2)
        self.set_font('Arial', '', 9)
        self.cell(30, 6, "Kaynak:", 0, 0); self.cell(60, 6, str(data.get('kaynak', '-')), 0, 0)
        self.cell(30, 6, "Matris:", 0, 0); self.cell(60, 6, str(data.get('matris', '-')), 0, 1)
        self.cell(30, 6, "Konsantrasyon:", 0, 0); self.set_font('Arial', 'B', 9)
        self.cell(60, 6, str(data.get('kons', '-')), 0, 0); self.set_font('Arial', '', 9)
        self.cell(30, 6, "Not:", 0, 0); self.multi_cell(0, 6, str(data.get('notlar', '')), 0, 'L')
        self.ln(5)
        self.set_fill_color(240, 255, 240)
        self.set_font('Arial', 'B', 12)
        self.cell(60, 10, f"C: {int(data.get('c',0))}", 1, 0, 'C', 1)
        self.cell(60, 10, f"T: {int(data.get('t',0))}", 1, 0, 'C', 1)
        self.cell(0, 10, f"Ratio: {data.get('oran','0')}", 1, 1, 'C', 1)
        self.ln(10)
        y = self.get_y()
        if data.get("res_dir"):
            f = glob.glob(os.path.join(data["res_dir"], "*_full_tespitler.jpg"))
            if f: self.image(f[0], x=30, y=y, h=80)
        if data.get("graph"): self.image(data["graph"], x=110, y=y+10, w=90)

# --- YARDIMCI FONKSİYONLAR ---
def ensure_dir(path):
    if not os.path.exists(path): os.makedirs(path)

def resim_oku_guvenli(path):
    try:
        with open(path, "rb") as f:
            bytes_data = bytearray(f.read())
            numpy_array = np.asarray(bytes_data, dtype=np.uint8)
            return cv2.imdecode(numpy_array, cv2.IMREAD_COLOR)
    except:
        return None

# --- GÖRÜNTÜ İŞLEME SINIFLARI ---
class ImagePreprocessor:
    def __init__(self, debug_folder=None): 
        self.dbg_folder = debug_folder
        
    def order_points(self, pts):
        rect = np.zeros((4, 2), dtype="float32")
        s = pts.sum(axis=1)
        rect[0] = pts[np.argmin(s)]
        rect[2] = pts[np.argmax(s)]
        diff = np.diff(pts, axis=1)
        rect[1] = pts[np.argmin(diff)]
        rect[3] = pts[np.argmax(diff)]
        return rect
        
    def find_markers(self, thresh_img, method_name):
        contours, _ = cv2.findContours(thresh_img, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        candidates = []
        for cnt in contours:
            if cv2.contourArea(cnt) < 300: continue
            peri = cv2.arcLength(cnt, True)
            approx = cv2.approxPolyDP(cnt, 0.04 * peri, True)
            if len(approx) == 4:
                _, _, w, h = cv2.boundingRect(approx)
                if 0.6 <= w/float(h) <= 1.4: # Kareye yakın olmalı
                    candidates.append(approx)
        return sorted(candidates, key=cv2.contourArea, reverse=True)[:4]
        
    def warp_image(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        _, t1 = cv2.threshold(blurred, 60, 255, cv2.THRESH_BINARY_INV)
        cnts = self.find_markers(t1, "global")
        if len(cnts) < 4:
            t2 = cv2.adaptiveThreshold(blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY_INV, 11, 2)
            cnts = self.find_markers(t2, "adaptive")
        if len(cnts) < 4: 
            return cv2.resize(image, (Config.STD_WIDTH, Config.STD_HEIGHT))
            
        pts = []
        for c in cnts:
            M = cv2.moments(c)
            if M["m00"] != 0:
                pts.append([int(M["m10"]/M["m00"]), int(M["m01"]/M["m00"])])
                
        if len(pts) != 4:
             return cv2.resize(image, (Config.STD_WIDTH, Config.STD_HEIGHT))
             
        src = self.order_points(np.array(pts, dtype="float32"))
        dst = np.array([[0,0], [Config.STD_WIDTH-1, 0], [Config.STD_WIDTH-1, Config.STD_HEIGHT-1], [0, Config.STD_HEIGHT-1]], dtype="float32")
        M = cv2.getPerspectiveTransform(src, dst)
        warped = cv2.warpPerspective(image, M, (Config.STD_WIDTH, Config.STD_HEIGHT))
        if self.dbg_folder: cv2.imwrite(os.path.join(self.dbg_folder, "01_duzeltilmis.jpg"), warped)
        return warped
        
    def extract_strip(self, img):
        x,y,w,h = Config.ROI_TEST_STRIP
        if y+h > img.shape[0] or x+w > img.shape[1]: return img
        return img[y:y+h, x:x+w]

class Analyzer:
    def __init__(self, debug_folder=None): 
        self.dbg_folder = debug_folder
        
    def analyze(self, strip_img, custom_c_pos=None, custom_t_pos=None):
        gray = cv2.cvtColor(strip_img, cv2.COLOR_BGR2GRAY)
        wp = np.percentile(gray, 95)
        bp = np.percentile(gray, 2)
        
        if wp-bp > 10:
            s = np.clip((gray-bp)/(wp-bp)*255, 0, 255).astype(np.uint8)
        else:
            s = gray
            
        if self.dbg_folder: cv2.imwrite(os.path.join(self.dbg_folder, "04_isik.jpg"), s)
        inv = 255 - s
        prof = np.mean(inv, axis=1)
        base = np.percentile(prof, 10)
        prof_c = np.maximum(0, prof - base)
        prof_n = (prof_c / 255.0) * 100
        
        peaks, _ = find_peaks(prof_n, height=Config.PEAK_HEIGHT, distance=Config.PEAK_DISTANCE, prominence=Config.PEAK_PROMINENCE)
        results = []
        c_auc = t_auc = None
        
        # Manuel Müdahale Modu
        if custom_c_pos is not None and custom_t_pos is not None:
            search_window = 10
            # C Hattı
            c_s = max(0, custom_c_pos - search_window)
            c_e = min(len(prof_n), custom_c_pos + search_window)
            c_reg = prof_n[c_s:c_e]
            if len(c_reg) > 0:
                pk = c_s + np.argmax(c_reg)
                s_idx = max(0, pk - Config.AUC_WINDOW_RADIUS)
                e_idx = min(len(prof_n), pk + Config.AUC_WINDOW_RADIUS + 1)
                c_auc = np.sum(prof_n[s_idx:e_idx])
                results.append({"peak_idx": pk, "height": prof_n[pk], "auc": c_auc, "label": "C"})
            
            # T Hattı
            t_s = max(0, custom_t_pos - search_window)
            t_e = min(len(prof_n), custom_t_pos + search_window)
            t_reg = prof_n[t_s:t_e]
            if len(t_reg) > 0:
                pk = t_s + np.argmax(t_reg)
                s_idx = max(0, pk - Config.AUC_WINDOW_RADIUS)
                e_idx = min(len(prof_n), pk + Config.AUC_WINDOW_RADIUS + 1)
                t_auc = np.sum(prof_n[s_idx:e_idx])
                results.append({"peak_idx": pk, "height": prof_n[pk], "auc": t_auc, "label": "T"})
        else:
            # Otomatik Mod
            for p in peaks:
                lbl = None
                for name, info in Config.LINE_LOCATIONS.items():
                    if info["pos"]-Config.POS_TOLERANCE <= p <= info["pos"]+Config.POS_TOLERANCE: 
                        lbl = name
                        break
                if not lbl: continue
                
                s_idx = max(0, p - Config.AUC_WINDOW_RADIUS)
                e_idx = min(len(prof_n), p + Config.AUC_WINDOW_RADIUS + 1)
                auc = np.sum(prof_n[s_idx:e_idx])
                if lbl=="C": c_auc = auc
                if lbl=="T": t_auc = auc
                results.append({"peak_idx": p, "height": prof_n[p], "auc": auc, "label": lbl})
        
        ratio = f"{t_auc/c_auc:.4f}" if (c_auc and t_auc and c_auc > 0) else "0.0000"
        raw_vals = {"c_auc": c_auc or 0.0, "t_auc": t_auc or 0.0}
        return prof_n, peaks, results, ratio, raw_vals
    
    def create_plots(self, folder, fname, warped, strip, prof, peaks, results, ratio):
        vis = warped.copy()
        x,y,w,h = Config.ROI_TEST_STRIP
        cv2.rectangle(vis, (x,y), (x+w, y+h), (255,255,0), 2)
        
        for r in results:
            py = int(r["peak_idx"] + y)
            color = (0,255,0) if r["label"]=="C" else (0,0,255)
            cv2.line(vis, (x, py), (x+w, py), color, 3)
            cv2.putText(vis, r["label"], (x-20, py), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            
        full_path = os.path.join(folder, f"{fname}_full_tespitler.jpg")
        cv2.imwrite(full_path, vis)
        
        plt.figure(figsize=(8,4))
        plt.ylim(0,100)
        plt.plot(prof, color='gray')
        for r in results:
            color = 'green' if r["label"]=="C" else 'red'
            plt.plot(r["peak_idx"], r["height"], "x", color=color)
            
        plt.title(f"{fname} | Ratio: {ratio}")
        plt.tight_layout()
        gp = os.path.join(folder, f"{fname}_graph.png")
        plt.savefig(gp)
        plt.close()
        return gp, full_path

# --- MOTOR ÇALIŞTIRMA (ÖZET) ---
def motoru_calistir(image_path, calisma_adi="Genel", hasta_id="Anonim", kaynak="Bilinmiyor", matris="Bilinmiyor", konsantrasyon=0.0, notlar="", output_basedir=None):
    if output_basedir is None: output_basedir = Config.BASE_OUTPUT_DIR
    filename = os.path.basename(image_path)
    base = os.path.splitext(filename)[0]
    ts = time.strftime("%Y%m%d_%H%M%S")
    s_dir = os.path.join(output_basedir, f"{hasta_id}_{ts}")
    ensure_dir(s_dir)
    
    db = DatabaseManager(Config.DB_NAME)
    pre = ImagePreprocessor(s_dir)
    ana = Analyzer(s_dir)
    
    try:
        img = resim_oku_guvenli(image_path)
        if img is None: return {"success": False, "error": "Dosya okunamadı"}
        
        warped = pre.warp_image(img)
        strip = pre.extract_strip(warped)
        prof, peaks, res, ratio, raw = ana.analyze(strip)
        gp, fp = ana.create_plots(s_dir, base, warped, strip, prof, peaks, res, ratio)
        
        db.kaydet(calisma_adi, hasta_id, filename, kaynak, matris, konsantrasyon, notlar, raw["c_auc"], raw["t_auc"], ratio, s_dir, gp)
        
        return {
            "success": True, 
            "filename": filename, 
            "ratio": ratio, 
            "c_val": raw["c_auc"], 
            "t_val": raw["t_auc"], 
            "graph_path": gp, 
            "full_img_path": fp, 
            "output_dir": s_dir,
            "hid": hasta_id,
            "kons": konsantrasyon
        }
    except Exception as e:
        print(f"!!! MOTOR HATASI: {e}")
        return {"success": False, "error": str(e)}

def tekil_yeniden_analiz(image_path, output_dir, c_pos, t_pos):
    filename = os.path.basename(image_path)
    base = os.path.splitext(filename)[0]
    pre = ImagePreprocessor(output_dir)
    ana = Analyzer(output_dir)
    db = DatabaseManager(Config.DB_NAME)
    
    try:
        img = resim_oku_guvenli(image_path)
        warped = pre.warp_image(img)
        strip = pre.extract_strip(warped)
        
        # Manuel Pozisyonla Analiz
        prof, peaks, res, ratio, raw = ana.analyze(strip, custom_c_pos=c_pos, custom_t_pos=t_pos)
        gp, fp = ana.create_plots(output_dir, base, warped, strip, prof, peaks, res, ratio)
        
        db.sonuc_guncelle(filename, raw["c_auc"], raw["t_auc"], ratio, gp)
        
        return {"success": True, "c_val": raw["c_auc"], "t_val": raw["t_auc"], "ratio": ratio, "graph_path": gp}
    except Exception as e:
        return {"success": False, "error": str(e)}

def toplu_pdf_olustur(veriler, yol):
    try:
        pdf = PDFRapor()
        pdf.alias_nb_pages()
        for d in veriler:
            if d.get('status') == 'done':
                pdf.add_patient_page(d)
        pdf.output(yol)
        return True, "PDF Olusturuldu"
    except Exception as e:
        return False, str(e)