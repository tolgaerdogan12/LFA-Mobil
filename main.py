import time
import os
import requests
import threading

from kivy.app import App
from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.label import Label
from kivy.uix.camera import Camera
from kivy.uix.popup import Popup
from kivy.uix.floatlayout import FloatLayout
from kivy.clock import Clock
from kivy.utils import platform
from kivy.storage.jsonstore import JsonStore

# Android İzinleri
if platform == "android":
    from android.permissions import request_permissions, Permission
    request_permissions([
        Permission.READ_EXTERNAL_STORAGE, 
        Permission.WRITE_EXTERNAL_STORAGE, 
        Permission.CAMERA,
        Permission.INTERNET
    ])

# Arayüz Tasarımı (Basit ve Sağlam)
KV = """
<CameraPopup>:
    title: "Kamerayi Hizala"
    size_hint: 0.9, 0.9
    auto_dismiss: False

    FloatLayout:
        Camera:
            id: camera
            resolution: (1280, 720)
            play: True
            allow_stretch: True
            keep_ratio: True
            pos_hint: {'center_x': 0.5, 'center_y': 0.5}

        # Yeşil Kutu Çizimi (Resim dosyasına gerek yok)
        Widget:
            canvas:
                Color:
                    rgba: 0, 1, 0, 0.5
                Line:
                    width: 3
                    rectangle: (self.parent.center_x - 150, self.parent.center_y - 250, 300, 500)

        Button:
            text: "IPTAL"
            size_hint: None, None
            size: 80, 50
            pos_hint: {'right': 0.95, 'top': 0.95}
            on_release: root.dismiss()

        Button:
            text: "CEK"
            size_hint: None, None
            size: 100, 100
            background_color: 1, 0, 0, 1
            pos_hint: {'center_x': 0.5, 'y': 0.05}
            on_release: root.capture()

BoxLayout:
    orientation: 'vertical'
    padding: 20
    spacing: 15
    canvas.before:
        Color:
            rgba: 0.1, 0.1, 0.1, 1
        Rectangle:
            pos: self.pos
            size: self.size

    Label:
        text: "LFA WIFI CLIENT"
        font_size: '24sp'
        bold: True
        size_hint_y: None
        height: 50
        color: 0.2, 0.6, 0.8, 1

    TextInput:
        id: txt_ip
        hint_text: "PC IP Adresi (Orn: 192.168.1.35)"
        multiline: False
        size_hint_y: None
        height: 50
        write_tab: False

    TextInput:
        id: txt_study
        hint_text: "Calisma Adi"
        text: "Wifi_Test"
        multiline: False
        size_hint_y: None
        height: 50
        write_tab: False

    TextInput:
        id: txt_id
        hint_text: "Numune ID"
        text: "01"
        multiline: False
        size_hint_y: None
        height: 50
        write_tab: False

    TextInput:
        id: txt_conc
        hint_text: "Konsantrasyon"
        text: "0"
        multiline: False
        size_hint_y: None
        height: 50
        write_tab: False

    Button:
        text: "KAMERAYI AC"
        size_hint_y: None
        height: 60
        background_color: 0.2, 0.4, 0.6, 1
        on_release: app.open_camera()

    Label:
        id: lbl_status
        text: "Hazir..."
        color: 0.8, 0.8, 0.8, 1
        size_hint_y: None
        height: 30

    Button:
        id: btn_send
        text: "GONDER"
        size_hint_y: None
        height: 60
        disabled: True
        background_color: 0.2, 0.7, 0.3, 1
        on_release: app.send_to_server()

    Label:
        id: lbl_result
        text: "Sonuc Bekleniyor..."
        color: 1, 1, 0, 1
"""

class CameraPopup(Popup):
    def capture(self):
        try:
            camera = self.ids['camera']
            timestr = time.strftime("%Y%m%d_%H%M%S")
            
            # Güvenli Kayıt Yeri
            if platform == 'android':
                from android.storage import app_storage_path
                save_dir = app_storage_path()
            else:
                save_dir = "LFA_Captures"
            
            if not os.path.exists(save_dir): os.makedirs(save_dir)
            filename = os.path.join(save_dir, f"IMG_{timestr}.png")
            camera.export_to_png(filename)
            
            app = App.get_running_app()
            app.on_picture_taken(filename)
            self.dismiss()
        except Exception as e:
            print(f"Kamera Hatasi: {e}")

class LFAApp(App):
    def build(self):
        self.selected_path = None
        self.store = JsonStore('settings.json')
        return Builder.load_string(KV)

    def on_start(self):
        # Kayıtlı IP ve Çalışma adını getir
        if self.store.exists('config'):
            conf = self.store.get('config')
            self.root.ids.txt_ip.text = conf.get('ip', '')
            self.root.ids.txt_study.text = conf.get('study', 'Wifi_Test')

    def open_camera(self):
        CameraPopup().open()

    def on_picture_taken(self, path):
        self.selected_path = path
        self.root.ids.lbl_status.text = "Fotograf Hazir"
        self.root.ids.btn_send.disabled = False

    def send_to_server(self):
        ip = self.root.ids.txt_ip.text
        if not ip:
            self.root.ids.lbl_status.text = "HATA: IP Giriniz!"
            return

        # Ayarlari hafızaya at
        self.store.put('config', ip=ip, study=self.root.ids.txt_study.text)
        
        url = f"http://{ip}:8000/analyze"
        self.root.ids.lbl_status.text = "Sunucuya Gonderiliyor..."
        
        # UI donmasın diye thread açıyoruz
        threading.Thread(target=self._send_thread, args=(url,)).start()

    def _send_thread(self, url):
        try:
            with open(self.selected_path, 'rb') as f:
                data = {
                    'study': self.root.ids.txt_study.text,
                    'hid': self.root.ids.txt_id.text,
                    'conc': self.root.ids.txt_conc.text
                }
                # Timeout 10 saniye
                resp = requests.post(url, files={'file': f}, data=data, timeout=10)
            
            if resp.status_code == 200:
                res = resp.json()
                Clock.schedule_once(lambda dt: self.show_result(res))
            else:
                Clock.schedule_once(lambda dt: self.set_status(f"HTTP Hata: {resp.status_code}"))
        except Exception as e:
            Clock.schedule_once(lambda dt: self.set_status(f"Baglanti Yok: {e}"))

    def set_status(self, txt):
        self.root.ids.lbl_status.text = str(txt)

    def show_result(self, res):
        if res.get("success"):
            info = f"C: {int(res['c_val'])} | T: {int(res['t_val'])}\nORAN: {res['ratio']}"
        else:
            info = f"Hata: {res.get('error')}"
        self.root.ids.lbl_result.text = info
        self.root.ids.lbl_status.text = "Analiz Tamamlandi"

if __name__ == "__main__":
    LFAApp().run()