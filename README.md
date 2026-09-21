# tube2note — YouTube videolarını yazıya çevir

[![PyPI](https://img.shields.io/pypi/v/tube2note)](https://pypi.org/project/tube2note/)
[![Site](https://img.shields.io/badge/site-tube2note.github.io-blue)](https://omersusin.github.io/tube2note/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green)](LICENSE)

YouTube'daki bir kanalın, oynatma listesinin veya videoların **konuşmalarını yazıya döker** ve düzenli dosyalar hâlinde verir. Ders çalışmak, araştırma yapmak veya videoları NotebookLM gibi yapay zekâ araçlarına vermek için birebirdir.

🌐 **Site:** https://omersusin.github.io/tube2note/ · 🐙 **Kaynak kod:** https://github.com/omersusin/tube2note

> **Teknik bilgin yoksa korkma.** Aşağıdaki adımları sırayla uygula, 10 dakikada ilk dosyan elinde olur.

---

## İçindekiler

- [Bu program ne yapar?](#bu-program-ne-yapar)
- [Kurulum: Android (telefon)](#kurulum-android-telefon)
- [Kurulum: Bilgisayar (Windows / Mac / Linux)](#kurulum-bilgisayar-windows--mac--linux)
- [İlk kullanım (adım adım)](#i̇lk-kullanım-adım-adım)
- [Günlük kullanım örnekleri](#günlük-kullanım-örnekleri)
- [Sık sorulan sorular](#sık-sorulan-sorular)
- [Sorun çıkarsa](#sorun-çıkarsa)
- [İleri düzey (opsiyonel)](#i̇leri-düzey-opsiyonel)

---

## Bu program ne yapar?

1. Bir YouTube bağlantısı verirsin (video, kanal veya liste).
2. Program videolardaki konuşmaları indirir, temizler, tek bir okunabilir dosya yapar.
3. Bu dosyayı **NotebookLM'e kaynak olarak verirsin** ve videolar hakkında sorular sorarsın.

Örnek: 200 videoluk bir ders kanalını bir dosyaya çevirirsin, sonra "3. derste ne anlatıldı?" diye sorarsın.

Teknik detaylar (geliştiriciler için): [MCP sunucusu](#i̇leri-düzey-opsiyonel), [Python API](#i̇leri-düzey-opsiyonel), [kaynak kod](https://github.com/omersusin/tube2note).

---

## Kurulum: Android (telefon)

Telefonda çalışması için **Termux** adlı ücretsiz uygulamayı kullanıyoruz.

### 1. Termux'u kur

- **F-Droid'den kur** (önerilir): [f-droid.org](https://f-droid.org) sitesinden F-Droid'i indir, sonra F-Droid içinden **Termux**'u kur.
- Play Store'daki Termux eskidir, onu kullanma.

### 2. Gerekli şeyleri kur

Termux'u aç ve şu satırları **tek tek** yazıp her birinden sonra Enter'a bas:

```bash
pkg update
pkg install python
pip install tube2note
```

Biraz bekle, kurulum bitsin.

### 3. Kontrol et

```bash
tube2note doctor
```

Ekranda bir kontrol listesi çıkar. Her şey yolundaysa kurulum tamamdır. 🎉

> **İpucu:** Uzun işler (büyük kanallar) gece çalışsın istersen, başlamadan önce `termux-wake-lock` yaz — telefon uykuya geçmez.

---

## Kurulum: Bilgisayar (Windows / Mac / Linux)

### 1. Python'u kur (yoksa)

- [python.org/downloads](https://www.python.org/downloads/) adresinden indir ve kur.
- Kurarken **"Add python.exe to PATH"** kutusunu işaretle (Windows).
- Kontrol: terminali/komut satırını aç, `python --version` yaz. Bir sürüm numarası görmelisin.

### 2. Programı kur

Terminalde (Windows: PowerShell veya CMD, Mac/Linux: Terminal):

```bash
pip install tube2note
```

### 3. Kontrol et

```bash
tube2note doctor
```

Her şey yolundaysa hazırsın. 🎉

---

## İlk kullanım (adım adım)

En kolayı **rehberli moddur**. Sadece şunu yaz:

```bash
tube2note
```

Program sana sorular sorar, sen cevaplarsın:

1. **Bağlantılar:** YouTube bağlantını yapıştır (birden fazla olabilir, araya boşluk koy).
2. **Dosya adı:** Çıktı dosyasının adını seç (önerileni kabul etmek için Enter).
3. **Klasör:** Dosyaların nereye kaydedileceğini seç.
4. **Ayarlar tablosu:** Dil, video sayısı gibi ayarları onayla.
5. **Başla:** Enter'a bas, program çalışsın.

İş bitince klasöründe `.md` uzantılı dosyan hazır. İlerleme çubuğunu ekranda görürsün.

> **Yarıda kesilirse sorun değil.** İnternet giderse veya uygulamayı kapatırsan, aynı komutu tekrar çalıştır — kaldığı yerden devam eder.

---

## Günlük kullanım örnekleri

Komut yazmaya alışınca bunları kopyala-yapıştır kullanabilirsin:

**Bir oynatma listesini indir:**
```bash
tube2note -o notlar.md "LİSTENİN_BAĞLANTISI"
```

**Bir kanalı klasörler hâlinde indir (her video ayrı dosya):**
```bash
tube2note -o kanal.md --layout tree -d ./notlarim "KANALIN_BAĞLANTISI"
```

**Önce ne çıkacağına bak (indirmeden tahmin):**
```bash
tube2note --dry-run "BAĞLANTI"
```

**Yeni videoları otomatik takip et:**
```bash
tube2note watch "KANALIN_BAĞLANTISI" -o kanal.md --interval 60
```
(İlk çalışta hepsini indirir, sonrakilerde sadece yeni videoları alır.)

**İndirdiklerinin içinde ara:**
```bash
tube2note search "aradığın kelime" -d ./notlarim
```

**E-kitap okuyucun için EPUB yap:**
```bash
tube2note epub notlar.md
```

**Telefondan tek dokunuşla devam et:** `tube2note widget` yaz (Termux:Widget uygulaması gerekir).

---

## Sık sorulan sorular

**NotebookLM'e nasıl veririm?**
NotebookLM'i aç → "Kaynak ekle" → bilgisayarından `.md` dosyasını yükle. Tek dosyada 500.000 kelime sınırı var; dosyan büyükse programı `--split-words 400000` seçeneğiyle çalıştır, parçalara böler.

**Altyazısı olmayan video ne olur?**
Atlanır ve `## Skipped` (Atlananlar) listesine yazılır. İstersen yapay zekâyla seslendirme yaptırabilirsin (İleri düzey bölümüne bak).

**Çok yavaş / durdu, ne yapayım?**
YouTube bazen hızı kısar. Program zaten otomatik yavaşlar ve bekler. Hiç ilerlemiyorsa kapat, **1 saat bekle**, tekrar çalıştır — kaldığı yerden devam eder.

**Bilgisayarım/telefonum kapandı, baştan mı?**
Hayır. Aynı komutu tekrar yaz, kaldığı yerden devam eder.

**İnternetteki siteden kullanabilir miyim?**
Sitedeki form, ayrıca kurulan bir sunucu gerektirir. En kolayı yukarıdaki kurulumu yapmaktır.

**Bu ücretsiz mi?**
Evet, tamamen ücretsiz ve açık kaynak (MIT). İsteğe bağlı yapay zekâ özellikleri Google'ın ücretsiz anahtarını kullanır.

---

## Sorun çıkarsa

| Sorun | Çözüm |
|---|---|
| `tube2note: command not found` | Kurulum yarım kalmış. Kurulum adımlarını baştan yap. |
| Saatlerce bekliyor, ilerlemiyor | Kapat, 1 saat bekle, tekrar çalıştır (YouTube hız kısmıştır). |
| `No subtitles` (altyazı yok) | O videoda altyazı yoktur, atlanır. Hepsi böyleyse `--transcribe` seçeneğine bak (İleri düzey). |
| Türkçe karakterler bozuk (`?` görünüyor) | `tube2note doctor` yaz, yazı tipi (font) satırına bak. |
| Yerim doldu | Telefon/bilgisayarında yer aç, tekrar çalıştır. Yarım dosyalar bozulmaz. |
| Hâlâ olmuyor | [Sorun bildir](https://github.com/omersusin/tube2note/issues) sayfasında anlat (Türkçe olur). |

---

## İleri düzey (opsiyonel)

Burası meraklılar ve geliştiriciler içindir. Normal kullanım için gerekmez.

**Komut satırı seçenekleri** (diller, bölme, temizlik ayarı, hız ayarı ve 40+ bayrak): `tube2note --help` yazarak tamamını görebilirsin. Önemliler: `--lang tr,en`, `--timestamps` (zaman damgası), `--link-timestamps` (tıklanabilir dakikalar), `--srt` (altyazı dosyası), `--split-words`, `--since YYYY-AA-GG`, `--resume-last`, `--redo VIDEO_ID, `--fresh`, `--proxy`, `--cookies`, `--cookies-from-browser chrome`, `--workers 2`.

**Yapay zekâ özellikleri** (ücretsiz `GEMINI_API_KEY` gerekir, [aistudio.google.com](https://aistudio.google.com)'dan alınır): `--transcribe` (altyazısız videoyu sese çevirir), `--summarize` (her videoya özet), `--translate tr` (çeviri), `--gemini-model` (model seçimi).

**İnternet tarayıcısından kullanma:** `tube2note serve` yaz — telefonda/bilgisayarda bir sayfa açılır, oradan yönetirsin.

**Obsidian kullanıyorsan:** `--obsidian --layout videos` ile notların etiket + takma ad içerir.

**E-kitap:** `--epub` bayrağı veya `tube2note epub dosya.md`.

**Otomasyon:** `tube2note status klasör --json`, çıkış kodları (0 = tamam, 1 = kısmi, 2 = hata), `YT2MD_*` ortam değişkenleri, `~/.config/yt2md/config.json` profilleri.

**Geliştiriciler:** `import tube2note.api` (collect/list/status), `tube2note mcp` (Claude/AI asistan bağlantısı), `tube2note serve-api` (site backend'i, FastAPI). Geliştirme: `pip install -e ".[dev]" && pytest && ruff check`. Sürüm etiketleri (`v*`) PyPI'ye otomatik yayınlanır.

## Lisans

MIT — bkz. [LICENSE](LICENSE).
