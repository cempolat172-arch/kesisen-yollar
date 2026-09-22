from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import json
import math
from datetime import datetime, timedelta, timezone

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def format_timestamp(ts):
    if not ts or ts == "Bilinmiyor" or ts == 0 or ts == "0":
        return "Tarih Bulunamadı"
    try:
        tr_tz = timezone(timedelta(hours=3))
        
        if isinstance(ts, (int, float)) or (isinstance(ts, str) and ts.isdigit()):
            ts_val = float(ts)
            if ts_val <= 0:
                return "Tarih Bulunamadı"
            if ts_val > 1e11:  # Milisaniye cinsindense
                ts_val /= 1000.0
            dt = datetime.fromtimestamp(ts_val, tz=timezone.utc).astimezone(tr_tz)
            if dt.year < 2010:  # 2010 öncesi hatalı/varsayılan tarihleri filtrele
                return "Tarih Bulunamadı"
            return dt.strftime("%d.%m.%Y %H:%M")
        elif isinstance(ts, str):
            clean_ts = ts.replace("Z", "+00:00")
            if "+" not in clean_ts and "T" in clean_ts:
                clean_ts += "+00:00"
            dt = datetime.fromisoformat(clean_ts)
            if dt.year < 2010:
                return "Tarih Bulunamadı"
            dt_tr = dt.astimezone(tr_tz)
            return dt_tr.strftime("%d.%m.%Y %H:%M")
    except Exception:
        pass
    return "Tarih Bulunamadı"

def parse_takeout(file_content: str):
    try:
        data = json.loads(file_content)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Geçersiz JSON formatı: {str(e)}")
    
    locations = []
    
    if isinstance(data, dict):
        items = data.get("timelineObjects", data.get("locations", []))
    elif isinstance(data, list):
        items = data
    else:
        items = []
        
    for item in items:
        if not isinstance(item, dict):
            continue
            
        if "visit" in item and isinstance(item["visit"], dict):
            visit = item["visit"]
            place_loc = visit.get("placeLocation", {})
            if isinstance(place_loc, dict) and "geo" in place_loc:
                geo_str = place_loc["geo"]
                if isinstance(geo_str, str) and geo_str.startswith("geo:"):
                    try:
                        lat_lng = geo_str.replace("geo:", "").split(",")
                        if len(lat_lng) == 2:
                            raw_time = visit.get("startTime", "Bilinmiyor")
                            locations.append({
                                "lat": float(lat_lng[0]),
                                "lng": float(lat_lng[1]),
                                "time": format_timestamp(raw_time)
                            })
                    except ValueError:
                        continue
                        
        if "timelinePath" in item and isinstance(item["timelinePath"], list):
            for path_point in item["timelinePath"]:
                if isinstance(path_point, dict) and "point" in path_point:
                    geo_str = path_point["point"]
                    if isinstance(geo_str, str) and geo_str.startswith("geo:"):
                        try:
                            lat_lng = geo_str.replace("geo:", "").split(",")
                            if len(lat_lng) == 2:
                                raw_time = path_point.get("durationMinutesOffsetFromStartTime", "Bilinmiyor")
                                locations.append({
                                    "lat": float(lat_lng[0]),
                                    "lng": float(lat_lng[1]),
                                    "time": format_timestamp(raw_time)
                                })
                        except ValueError:
                            continue
                            
        lat = item.get("latitudeE7")
        lng = item.get("longitudeE7")
        if lat and lng:
            locations.append({
                "lat": lat / 1e7,
                "lng": lng / 1e7,
                "time": format_timestamp(item.get("timestamp", "Bilinmiyor"))
            })
            
        lat_std = item.get("latitude")
        lng_std = item.get("longitude")
        if lat_std and lng_std:
            locations.append({
                "lat": float(lat_std),
                "lng": float(lng_std),
                "time": format_timestamp(item.get("timestamp", "Bilinmiyor"))
            })
            
    return locations

def calculate_distance(lat1, lon1, lat2, lon2):
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

@app.post("/api/compare-together")
async def compare_together(file1: UploadFile = File(...), file2: UploadFile = File(...)):
    content1 = await file1.read()
    content2 = await file2.read()
    
    locs1 = parse_takeout(content1.decode("utf-8", errors="ignore"))
    locs2 = parse_takeout(content2.decode("utf-8", errors="ignore"))
    
    matches = []
    for l1 in locs1:
        for l2 in locs2:
            dist = calculate_distance(l1["lat"], l1["lng"], l2["lat"], l2["lng"])
            if dist <= 100:
                matches.append({
                    "lat": round((l1["lat"] + l2["lat"]) / 2, 6),
                    "lng": round((l1["lng"] + l2["lng"]) / 2, 6),
                    "distance_meters": round(dist, 1),
                    "time1": l1["time"],
                    "time2": l2["time"]
                })
                
    return {
        "match_count": len(matches),
        "matches": matches[:30],
        "total_locs_1": len(locs1),
        "total_locs_2": len(locs2)
    }

@app.get("/", response_class=HTMLResponse)
async def index():
    return """
    <!DOCTYPE html>
    <html lang="tr">
    <head>
        <meta charset="UTF-8">
        <title>Kesişen Yollar</title>
        <script src="https://cdn.tailwindcss.com"></script>
        <style>
            @media print {
                body { background: white !important; color: black !important; }
                #uploadSection, #storySection, #paymentLockSection, .no-print { display: none !important; }
                #printReport { display: block !important; }
            }
        </style>
    </head>
    <body class="bg-slate-900 text-white min-h-screen flex flex-col items-center justify-center p-4">
        <div id="uploadSection" class="bg-slate-800 p-6 rounded-2xl shadow-xl w-full max-w-lg border border-pink-500/30">
            <h1 class="text-2xl font-bold mb-1 text-pink-500 text-center">Kesişen Yollar</h1>
            <p class="text-xs text-slate-400 text-center mb-4">Temizlenmiş Zaman Damgası & Hikaye Modu</p>
            
            <!-- Dosya Nasıl Alınır Bilgilendirme Kutusu -->
            <div class="mb-4 bg-slate-900/80 p-3 rounded-xl border border-slate-700 text-[11px] text-slate-300 space-y-1">
                <div class="font-bold text-pink-400 flex items-center gap-1">
                    <span>💡</span> Google Konum Geçmişi (JSON) Nasıl Yüklenir?
                </div>
                <div>1. <a href="https://takeout.google.com/" target="_blank" class="text-pink-400 underline font-semibold">Google Takeout</a> adresine gidin.</div>
                <div>2. Sadece **Konum Geçmişi (Timeline)** verisini seçerek dışa aktarın (JSON formatında).</div>
                <div>3. İndirdiğiniz JSON dosyasını aşağıdan seçip iki partner için yükleyin.</div>
            </div>

            <form id="uploadForm" class="space-y-3">
                <div>
                    <label class="block text-xs mb-1 text-slate-300">1. Partner Dosyası (.json)</label>
                    <input type="file" id="file1" class="w-full text-xs text-slate-400 file:mr-4 file:py-1.5 file:px-3 file:rounded-full file:border-0 file:text-xs file:font-semibold file:bg-pink-600 file:text-white hover:file:bg-pink-700"/>
                </div>
                <div>
                    <label class="block text-xs mb-1 text-slate-300">2. Partner Dosyası (.json)</label>
                    <input type="file" id="file2" class="w-full text-xs text-slate-400 file:mr-4 file:py-1.5 file:px-3 file:rounded-full file:border-0 file:text-xs file:font-semibold file:bg-pink-600 file:text-white hover:file:bg-pink-700"/>
                </div>
                <div class="flex gap-2 pt-2">
                    <button type="submit" class="flex-1 py-2.5 bg-gradient-to-r from-pink-500 to-rose-600 rounded-xl font-bold hover:opacity-90 transition text-xs shadow-lg">Kesişmeleri Analiz Et</button>
                </div>
            </form>
            
            <!-- Analiz Özet Bilgisi -->
            <div id="summaryResult" class="mt-4"></div>

            <!-- Shopier Ödeme ve Kilit Alanı (Başlangıçta Gizli, Analiz Sonrası Görünür) -->
            <div id="paymentLockSection" class="mt-6 hidden p-6 bg-gradient-to-r from-purple-900/90 to-pink-900/90 border border-pink-500/60 rounded-2xl text-center space-y-4 shadow-2xl">
                <div class="inline-flex items-center justify-center w-12 h-12 bg-pink-500/20 text-pink-400 rounded-full mb-1 text-xl">🔒</div>
                <h3 class="text-lg font-bold text-white">Raporu ve Hikaye Kartını Aç</h3>
                <p class="text-xs text-slate-300 max-w-md mx-auto">Tüm ortak kesişim noktalarınızı ve özel Instagram hikaye kartınızı görüntülemek için kilit ekranındasınız.</p>
                
                <!-- Kullanım Rehberi -->
                <div class="bg-slate-950/60 p-3 rounded-xl border border-pink-500/30 text-left space-y-1.5 text-[11px] text-slate-200">
                    <div class="font-bold text-pink-400 mb-1">📌 Nasıl Açılır?</div>
                    <div>1️⃣ Aşağıdaki **100 TL** güvenli ödeme butonuna tıkla ve ödemeyi tamamla.</div>
                    <div>2️⃣ Ödeme sonrasında sana verilen **Sipariş Numarasını** aşağıya yaz ve **"Sipariş No ile Aç"** butonuna bas!</div>
                </div>

                <a id="shopierBtn" href="https://www.shopier.com/kuyum/51088401" target="_blank" class="inline-flex items-center justify-center gap-2 px-8 py-3 bg-gradient-to-r from-pink-500 to-purple-600 hover:opacity-90 text-white rounded-xl font-bold text-xs shadow-lg transition transform hover:scale-105">
                    <span>💳 Güvenli Ödeme Yap (100 TL)</span>
                </a>

                <!-- Sipariş Numarası Giriş Alanı -->
                <div class="pt-2 border-t border-pink-500/20 space-y-2">
                    <label class="block text-[11px] text-pink-300 font-semibold">Shopier Sipariş Numaranızı Girin:</label>
                    <div class="flex gap-2">
                        <input type="text" id="orderNumberInput" placeholder="Örn: 849201" class="flex-1 px-3 py-2 bg-slate-900 border border-pink-500/40 rounded-xl text-xs text-white focus:outline-none focus:border-pink-500 text-center font-bold tracking-wider"/>
                        <button type="button" id="verifyOrderBtn" class="px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-xl font-bold text-xs transition shadow">Sipariş No ile Aç 🔓</button>
                    </div>
                    <div id="orderError" class="text-[10px] text-rose-400 hidden">Lütfen geçerli bir sipariş numarası girin!</div>
                </div>
            </div>

            <!-- Kilitli İçerikler (Ödeme Yapılmadan Önce Gizli) -->
            <div id="lockedContent" class="mt-6 hidden space-y-6">
                <!-- PDF İndirme ve Detaylar -->
                <div class="flex justify-between items-center bg-slate-900 p-3 rounded-xl border border-slate-700">
                    <span class="text-xs text-emerald-400 font-bold">✅ Sipariş Onaylandı & Kilit Açıldı!</span>
                    <button type="button" id="downloadPdfBtn" class="px-4 py-2 bg-slate-700 hover:bg-slate-600 rounded-xl font-bold text-xs transition border border-slate-600 text-white">PDF Raporu İndir 📄</button>
                </div>

                <!-- Detaylı Liste -->
                <div id="resultList" class="space-y-2 max-h-52 overflow-y-auto pr-1"></div>

                <!-- Instagram / TikTok Hikaye Şablonu -->
                <div id="storySection" class="flex flex-col items-center">
                    <h3 class="text-xs font-semibold text-pink-400 mb-2">📸 Instagram / TikTok Hikaye Kartı</h3>
                    <div class="w-72 h-[440px] bg-gradient-to-tr from-black via-zinc-900 to-rose-950 border-2 border-pink-500 rounded-3xl p-5 flex flex-col justify-between shadow-2xl text-center relative overflow-hidden">
                        <div class="absolute top-0 right-0 w-36 h-36 bg-pink-600/30 rounded-full blur-3xl"></div>
                        <div class="absolute bottom-0 left-0 w-36 h-36 bg-purple-600/30 rounded-full blur-3xl"></div>
                        
                        <div class="relative z-10">
                            <span class="text-[9px] tracking-widest uppercase text-pink-400 font-extrabold px-3 py-1 bg-pink-950/60 rounded-full border border-pink-500/40">KADERIN CIMRI OYUNU</span>
                            <h2 class="text-lg font-black mt-2 text-white tracking-wide">Yollarımız Hep Kesilmiş! ⚡</h2>
                        </div>
                        
                        <div class="relative z-10 my-auto space-y-2 bg-white/10 backdrop-blur-md p-3 rounded-2xl border border-white/20 shadow-inner">
                            <div class="text-3xl font-black text-pink-400 drop-shadow" id="storyCount">0</div>
                            <div class="text-[11px] text-white font-bold">Ortak Noktada Buluşuldu</div>
                            <div class="text-[10px] text-pink-200 border-t border-white/10 pt-1.5 mt-1" id="firstMatchDesc">
                                <span class="font-semibold text-white">İlk Karşılaşma:</span> Yükleniyor...
                            </div>
                        </div>
                        
                        <button id="shareStoryBtn" type="button" class="mt-2 w-full py-2.5 bg-gradient-to-r from-purple-600 to-pink-600 hover:opacity-90 text-white rounded-xl font-bold text-xs shadow-lg transition flex items-center justify-center gap-2 cursor-pointer"><span>Hikaye Görselini İndir / Paylaş 🚀</span></button>
                        <div class="relative z-10 flex justify-between items-center text-[9px] text-slate-400 px-1 border-t border-white/10 pt-2">
                            <span class="font-bold text-pink-400">#KesişenYollar</span>
                            <span>Google Takeout AI</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Yazdırma / PDF İçin Gizli Rapor Alanı -->
        <div id="printReport" class="hidden p-8 text-black">
            <h1 class="text-2xl font-bold text-pink-600 mb-2">Kesişen Yollar - Analiz Raporu</h1>
            <p id="printMeta" class="text-sm text-gray-600 mb-4"></p>
            <table class="w-full border-collapse border border-gray-300 text-xs">
                <thead>
                    <tr class="bg-gray-100">
                        <th class="border border-gray-300 p-2">#</th>
                        <th class="border border-gray-300 p-2">Koordinat</th>
                        <th class="border border-gray-300 p-2">Mesafe</th>
                        <th class="border border-gray-300 p-2">Zaman (Partner 1)</th>
                        <th class="border border-gray-300 p-2">Zaman (Partner 2)</th>
                    </tr>
                </thead>
                <tbody id="printTableBody"></tbody>
            </table>
        </div>
        
        <script>
            let currentMatches = [];
            let lastMeta = {};

            window.addEventListener('DOMContentLoaded', () => {
                document.getElementById('verifyOrderBtn').onclick = () => {
                    const orderNo = document.getElementById('orderNumberInput').value.trim();
                    const errDiv = document.getElementById('orderError');
                    
                    if (orderNo && orderNo.length >= 3) {
                        localStorage.setItem('kesisen_odeme_yapildi', 'true');
                        localStorage.setItem('kesisen_siparis_no', orderNo);
                        errDiv.classList.add('hidden');
                        
                        if (currentMatches.length > 0) {
                            renderUnlockedContent({ matches: currentMatches, match_count: currentMatches.length });
                        } else {
                            alert('Sipariş numaranız kaydedildi! Lütfen analiz için dosyalarınızı yükleyin.');
                        }
                    } else {
                        errDiv.classList.remove('hidden');
                    }
                };

                // Yerel Canvas ile %100 Çalışan Hikaye Kartı İndirme
                document.getElementById('shareStoryBtn').onclick = () => {
                    const btn = document.getElementById('shareStoryBtn');
                    btn.innerText = "Görsel Hazırlanıyor... ⏳";
                    
                    try {
                        const canvas = document.createElement('canvas');
                        canvas.width = 1080;
                        canvas.height = 1920;
                        const ctx = canvas.getContext('2d');
                        
                        // Arka Plan Gradient
                        const bgGrad = ctx.createLinearGradient(0, 0, 1080, 1920);
                        bgGrad.addColorStop(0, '#000000');
                        bgGrad.addColorStop(0.5, '#18181b');
                        bgGrad.addColorStop(1, '#4c0519');
                        ctx.fillStyle = bgGrad;
                        ctx.fillRect(0, 0, 1080, 1920);
                        
                        // Üst Kategori Badge
                        ctx.fillStyle = 'rgba(131, 24, 66, 0.6)';
                        ctx.strokeStyle = 'rgba(236, 72, 153, 0.4)';
                        ctx.lineWidth = 4;
                        ctx.beginPath();
                        ctx.roundRect(290, 350, 500, 90, 45);
                        ctx.fill();
                        ctx.stroke();
                        
                        ctx.fillStyle = '#f472b6';
                        ctx.font = 'bold 28px sans-serif';
                        ctx.textAlign = 'center';
                        ctx.fillText('KADERİN CİMRİ OYUNU', 540, 408);
                        
                        // Ana Başlık
                        ctx.fillStyle = '#ffffff';
                        ctx.font = 'bold 64px sans-serif';
                        ctx.fillText('Yollarımız Hep Kesilmiş! ⚡', 540, 520);
                        
                        // Ortadaki Kutu (Card Container)
                        ctx.fillStyle = 'rgba(255, 255, 255, 0.08)';
                        ctx.strokeStyle = 'rgba(255, 255, 255, 0.2)';
                        ctx.lineWidth = 4;
                        ctx.beginPath();
                        ctx.roundRect(140, 680, 800, 560, 40);
                        ctx.fill();
                        ctx.stroke();
                        
                        // Sayaç Sayısı
                        ctx.fillStyle = '#f472b6';
                        ctx.font = 'bold 130px sans-serif';
                        const countText = document.getElementById('storyCount').innerText;
                        ctx.fillText(countText, 540, 840);
                        
                        ctx.fillStyle = '#ffffff';
                        ctx.font = 'bold 36px sans-serif';
                        ctx.fillText('Ortak Noktada Buluşuldu', 540, 910);
                        
                        // İlk Karşılaşma Detayı
                        ctx.fillStyle = '#fbcfe8';
                        ctx.font = '28px sans-serif';
                        ctx.fillText('İlk Karşılaşma:', 540, 1020);
                        
                        ctx.fillStyle = '#ffffff';
                        ctx.font = 'bold 26px sans-serif';
                        const firstDesc = document.getElementById('firstMatchDescText') ? document.getElementById('firstMatchDescText').innerText : 'Birlikte aynı yerden geçildi';
                        ctx.fillText(firstDesc, 540, 1075);
                        
                        // Alt Etiket
                        ctx.fillStyle = '#f472b6';
                        ctx.font = 'bold 32px sans-serif';
                        ctx.fillText('#KesişenYollar', 540, 1720);
                        
                        ctx.fillStyle = '#94a3b8';
                        ctx.font = '26px sans-serif';
                        ctx.fillText('Google Takeout AI', 540, 1770);
                        
                        // İndirme Tetikleme
                        const image = canvas.toDataURL('image/png');
                        const a = document.createElement('a');
                        a.href = image;
                        a.download = 'kesisen-yollar-hikaye.png';
                        a.click();
                        
                        btn.innerText = "Hikaye Görselini İndir / Paylaş 🚀";
                    } catch (err) {
                        alert('Görsel oluşturulurken bir hata oluştu.');
                        btn.innerText = "Hikaye Görselini İndir / Paylaş 🚀";
                    }
                };
            });

            document.getElementById('uploadForm').onsubmit = async (e) => {
                e.preventDefault();
                const f1 = document.getElementById('file1').files[0];
                const f2 = document.getElementById('file2').files[0];
                if(!f1 || !f2) { alert('Lütfen iki dosyayı da seçin!'); return; }
                
                const formData = new FormData();
                formData.append('file1', f1);
                formData.append('file2', f2);
                
                const summaryDiv = document.getElementById('summaryResult');
                summaryDiv.innerHTML = '<div class="text-center text-pink-400 animate-pulse text-xs font-semibold py-2">Sahte tarihler filtreleniyor, kesişmeler taranıyor...</div>';
                
                document.getElementById('paymentLockSection').classList.add('hidden');
                document.getElementById('lockedContent').classList.add('hidden');
                
                try {
                    const res = await fetch('/api/compare-together', { method: 'POST', body: formData });
                    const data = await res.json();
                    if(res.ok) {
                        currentMatches = data.matches;
                        lastMeta = data;
                        
                        let summaryHtml = `<div class="p-3 bg-slate-900 rounded-xl border border-slate-700 text-center space-y-1">
                            <h3 class="text-sm font-bold text-pink-400">Bulunan Kesişme: ${data.match_count}</h3>
                            <p class="text-[10px] text-slate-400">Partner 1: ${data.total_locs_1} | Partner 2: ${data.total_locs_2}</p>
                        </div>`;
                        summaryDiv.innerHTML = summaryHtml;
                        
                        if(data.match_count > 0) {
                            const isPaid = localStorage.getItem('kesisen_odeme_yapildi') === 'true';
                            
                            if (isPaid) {
                                renderUnlockedContent(data);
                            } else {
                                document.getElementById('paymentLockSection').classList.remove('hidden');
                            }
                        } else {
                            summaryDiv.innerHTML += '<p class="text-xs text-slate-400 text-center py-2">Belirtilen mesafe aralığında kesişme bulunamadı.</p>';
                        }
                    } else {
                        summaryDiv.innerHTML = `<div class="p-2 bg-red-900/50 text-red-300 rounded-lg text-xs text-center">Hata: ${data.detail || 'Bilinmeyen hata'}</div>`;
                    }
                } catch(err) {
                    summaryDiv.innerHTML = `<div class="p-2 bg-red-900/50 text-red-300 rounded-lg text-xs text-center">Bağlantı hatası oluştu!</div>`;
                }
            };

            function renderUnlockedContent(data) {
                document.getElementById('paymentLockSection').classList.add('hidden');
                document.getElementById('lockedContent').classList.remove('hidden');
                
                let listHtml = '';
                data.matches.forEach((m, idx) => {
                    listHtml += `<div class="p-2.5 bg-slate-800 rounded-lg border border-slate-700 text-xs space-y-1">
                        <div class="flex justify-between font-bold text-rose-400 text-[11px]">
                            <span>#${idx + 1} Kesişme Noktası</span>
                            <span class="bg-rose-950 px-1.5 py-0.5 rounded text-[10px]">Mesafe: ${m.distance_meters} m</span>
                        </div>
                        <div class="text-slate-300 font-mono text-[10px]">📍 ${m.lat}, ${m.lng}</div>
                        <div class="grid grid-cols-2 gap-1 text-[10px] text-slate-300 bg-slate-950/50 p-1.5 rounded">
                            <div>P1: <span class="text-pink-400">${m.time1}</span></div>
                            <div>P2: <span class="text-pink-400">${m.time2}</span></div>
                        </div>
                        <div class="pt-1">
                            <a href="https://www.google.com/maps?q=${m.lat},${m.lng}" target="_blank" class="block text-center w-full py-1 bg-pink-600 text-white rounded hover:bg-pink-700 font-bold transition text-[10px]">Haritada Gör 📍</a>
                        </div>
                    </div>`;
                });
                document.getElementById('resultList').innerHTML = listHtml;
                document.getElementById('storyCount').innerText = data.match_count;
                
                if (data.matches.length > 0) {
                    const first = data.matches[0];
                    document.getElementById('firstMatchDesc').innerHTML = `<span class="font-semibold text-white">İlk Karşılaşma:</span> <span id="firstMatchDescText">${first.time1}</span>`;
                }
            }

            document.getElementById('downloadPdfBtn').onclick = () => {
                const tbody = document.getElementById('printTableBody');
                tbody.innerHTML = '';
                currentMatches.forEach((m, idx) => {
                    tbody.innerHTML += `<tr>
                        <td class="border border-gray-300 p-2 text-center">${idx + 1}</td>
                        <td class="border border-gray-300 p-2 font-mono">${m.lat}, ${m.lng}</td>
                        <td class="border border-gray-300 p-2 text-center">${m.distance_meters} m</td>
                        <td class="border border-gray-300 p-2">${m.time1}</td>
                        <td class="border border-gray-300 p-2">${m.time2}</td>
                    </tr>`;
                });
                document.getElementById('printMeta').innerText = `Toplam Kesişme: ${lastMeta.match_count} | Partner 1: ${lastMeta.total_locs_1} kayıt | Partner 2: ${lastMeta.total_locs_2} kayıt`;
                window.print();
            };
        </script>
    </body>
    </html>
    """