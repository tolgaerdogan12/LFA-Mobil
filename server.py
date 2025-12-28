# Dosya Adı: server.py
# Açıklama: PC'yi Analiz Sunucusu Yapar

from fastapi import FastAPI, File, UploadFile, Form
import uvicorn
import shutil
import os
import lfa_motoru  # Bizim motor

app = FastAPI()

# Geçici klasör
UPLOAD_DIR = "temp_server_uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.post("/analyze")
async def analyze_image(
    file: UploadFile = File(...),
    study: str = Form(...),
    hid: str = Form(...),
    conc: str = Form(...)
):
    try:
        # 1. Gelen resmi kaydet
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        print(f"📥 Yeni İstek Geldi: {file.filename} -> {study}")

        # 2. Motoru Çalıştır (PC gücüyle!)
        res = lfa_motoru.motoru_calistir(
            image_path=file_path,
            calisma_adi=study,
            hasta_id=hid,
            kaynak="Mobil_WiFi",
            matris="Bilinmiyor",
            konsantrasyon=conc,
            notlar="Server_Side_Analysis"
        )
        
        # 3. Sonucu JSON olarak döndür
        return res

    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    # 0.0.0.0 demek: "Ağdaki herkes bana ulaşabilsin" demek.
    uvicorn.run(app, host="0.0.0.0", port=8000)