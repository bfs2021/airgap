# PRD — AirGap

> **Local-first Veri Governance & PII Lineage Denetçisi**
> DataHub Agent Hackathon · Wildcard (Regulatory Automation) · v0.1 (taslak)
> Tarih: 2026-08-03 · Deadline: 2026-08-10

---

## 1. Info 

DataHub'daki metadata'yı (PII/hassas tag'ler, glossary term'leri, column-level sınıflandırma, lineage, ownership) okuyup **hassas verinin downstream'de etiketsiz / sahipsiz / politikasız yerlere sızdığı "governance leak"leri** tespit eden; bulguları **tamamen local (Ollama)** bir agent ile insan diline çevirip önceliklendirilmiş risk raporu + düzeltme artefaktları üreten bir araç.

---

## 2. Problem

Modern veri stack'inde PII bir yerde doğru etiketlenir (ör. `users.email` → `PII`), ama o veri onlarca transform, dashboard ve ML feature'ına akarken **sınıflandırma taşınmaz**. Sonuç:

- PII, tag'siz downstream tablolara/dashboard'lara sızar → GDPR/KVKK ihlali riski.
- Bu türev varlıkların **sahibi yoktur** → ihlal olduğunda kime sorulacağı belirsiz.
- Denetim manuel, lineage grafiğini elle gezerek yapılır → ölçeklenmez.
- Otomatikleştirmek için metadata'yı bir cloud LLM'e yollamak, **denetlenen gizli veriyi bir başka üçüncü tarafa açmak** demektir — yani araç, çözmeye çalıştığı problemi yaratır.

**Boşluk:** Governance denetimini otomatikleştiren ama bunu veriyi dışarı çıkarmadan yapan bir agent yok.

---

## 3. Çözüm & Değer Önermesi

**AirGap** DataHub'ı context kaynağı olarak kullanır, lineage'ı programatik olarak gezer, PII yayılımını izler ve ihlalleri bulur. Yorumlama/raporlama katmanı **local Ollama** ile çalışır → **hiçbir metadata makineyi terk etmez.**

Fark yaratan tek cümle: **"Gizliliği denetleyen aracın kendisi de gizli."**

---

## 4. Hedef Kullanıcı

| Persona | İhtiyaç |
|---|---|
| Data Governance / Compliance lead | "PII'ımız nereye sızıyor, kim sorumlu, kanıtı ver." |
| Data Platform engineer | "CI'da governance kontrolü, elle lineage gezmeden." |
| Data Protection Officer (DPO) | "Denetlenebilir, offline, veri dışarı çıkmayan bir rapor." |

---

## 5. Hedefler / Hedef Olmayanlar

### Goals
- G1: DataHub'dan (hosted demo) dataset + tag + glossary + column-level metadata + lineage okumak.
- G2: PII/hassas sınıflandırılmış kaynaklardan downstream'e lineage traversali yapmak.
- G3: "Governance leak" kurallarını uygulamak (etiketsiz PII yayılımı, sahipsiz hassas varlık, kırık classification zinciri).
- G4: Local Ollama ile her bulguyu açıklayan + önceliklendiren + düzeltme öneren rapor üretmek.
- G5: Düzeltme artefaktları üretmek (DataHub Python SDK / YAML patch) — read-only demo'da *önerilen değişiklik* olarak.
- G6: <3dk demo videosu + public repo (Apache 2.0) + çalışan CLI/rapor.

### Non-Goals
- DataHub'a canlı yazma (hosted demo read-only; yazma artefakt olarak üretilir, uygulanmaz).
- Kendi metadata katalog motorunu yazmak (DataHub'ı kullanıyoruz, kopyalamıyoruz).
- Gerçek zamanlı streaming denetim (batch/on-demand yeterli).
- Prod-grade auth/multi-tenant (hackathon scope).

---

## 6. Başarı Kriterleri 

- **S1 (fonksiyonel):** Demo katalogda en az 3 gerçek governance leak'i doğru tespit edip lineage yoluyla açıklayabiliyor.
- **S2 (local):** Uçtan uca çalışma sırasında ağ trafiği yalnızca DataHub API'sine; LLM çağrılarının tamamı localhost:11434 (Ollama).
- **S3 (artefakt):** Her ihlal için makine-okur (JSON) + insan-okur (Markdown) rapor + en az 1 düzeltme patch örneği `examples/` altında.
- **S4 (demo):** Judge repoyu klonlayıp `README` adımlarıyla tek komutla raporu üretebiliyor.

---

## 7. Mimari & Entegrasyon

```
┌────────────────────┐     GraphQL/MCP (read-only, HTTPS)
│  DataHub (hosted    │◄─────────────────────────────┐
│  demo.datahub.com)  │                              │
└────────────────────┘                              │
                                          ┌──────────┴───────────┐
                                          │   Sentinel Agent     │
                                          │  (Python)            │
                                          │                      │
   ┌──────────────────┐   localhost:11434 │  1. Fetch metadata   │
   │  Ollama (local)  │◄──────────────────│  2. Traverse lineage │
   │  llama3.1 / qwen │──────────────────►│  3. Apply leak rules │
   └──────────────────┘   (yorum+rapor)   │  4. LLM açıklama     │
                                          │  5. Emit report+patch│
                                          └──────────┬───────────┘
                                                     │
                                      ┌──────────────┴──────────────┐
                                      │  outputs/                    │
                                      │  - findings.json             │
                                      │  - report.md                 │
                                      │  - patches/*.py|*.yaml       │
                                      │  - lineage_graph.html (görsel)│
                                      └─────────────────────────────┘
```

### 7.1 DataHub Entegrasyonu
- **Kaynak:** `demo.datahub.com` (hosted demo, read-only).
- **Erişim yöntemi (öncelik sırası):**
  1. **DataHub MCP Server** — varsa agent bunun üzerinden okur (hackathon'un teşvik ettiği yol).
  2. **GraphQL API** (`/api/graphql`) — fallback; dataset, tag, glossaryTerms, schemaMetadata (fieldPath + tags), ownership, upstream/downstream lineage sorguları.
  3. **DataHub Python SDK** (`acryl-datahub`) — patch/artefakt üretimi için.
- **Okunacak metadata:** dataset URN, platform, schema field'ları, field-level tag/glossary, dataset-level tag, owners, upstream/downstream lineage edge'leri.

### 7.2 Ollama Entegrasyonu
- Local HTTP (`http://localhost:11434`).
- Model: `llama3.1:8b` veya `qwen2.5` (kod/JSON üretiminde iyi). Config'ten değiştirilebilir.
- Rol: (a) her bulgu için düz-dil açıklama, (b) severity gerekçesi, (c) düzeltme adımı önerisi. **Tespit mantığı deterministik kod**; LLM yalnızca yorumlama/iletişim katmanı → halüsinasyon riski düşük, sonuç tekrarlanabilir.

### 7.3 Governance Leak Kuralları (deterministik çekirdek)
- **R1 — Untagged PII propagation:** PII-tag'li bir field'dan lineage ile ulaşılan downstream dataset'te karşılık gelen sınıflandırma/tag yok.
- **R2 — Ownerless sensitive asset:** Hassas veri taşıyan (doğrudan veya türev) dataset'in owner'ı yok.
- **R3 — Broken classification chain:** Upstream'de var olan glossary term'i downstream'de kayboluyor.
- **R4 — Policy gap (opsiyonel):** PII içeren varlıkta domain/data-contract/retention politikası eksik.

Her kural: `severity` (blast-radius = etkilenen downstream sayısı × consumer türü), `evidence` (lineage yolu), `remediation` (önerilen patch) üretir.

---

## 8. Özellikler (öncelik sırası)

- **P0** DataHub'dan metadata + lineage çekme (MCP → GraphQL fallback).
- **P0** R1 + R2 kuralları + blast-radius severity.
- **P0** `findings.json` + `report.md` üretimi.
- **P0** Ollama ile bulgu açıklama katmanı.
- **P1** Görsel lineage grafiği (HTML, leak'ler kırmızı vurgulu).
- **P1** Düzeltme patch üreteci (DataHub SDK Python snippet + YAML).
- **P2** R3 + R4 kuralları.
- **P2** CI modu (exit code ≠ 0 eğer CRITICAL bulgu varsa).

---

## 9. Deliverable ↔ Hackathon Gereksinimi Eşlemesi

| Hackathon ister | Sentinel karşılığı |
|---|---|
| Çalışan uygulama + kolay test | Tek komut CLI: `sentinel audit --domain <x>` |
| Public repo + Apache 2.0 | GitHub public repo, LICENSE (About'ta görünür) |
| Metin açıklaması | README + bu PRD |
| <3dk demo video (YouTube/Vimeo public) | Katalogda gerçek leak tespiti ekran kaydı |
| (Ops.) Sample outputs | `examples/`: findings.json, report.md, patch örnekleri |
| DataHub'ı foundation olarak kullan | MCP/GraphQL ile okuma + SDK ile patch |

---

## 10. Kapsam 

**Kapsam kararı:** P0 özellikler + görsel grafik hedef. R3/R4 kuralları (§8 P2) ve CI modu **stretch** — sadece zaman kalırsa. Deterministik çekirdek her koşulda çalışır; LLM ve görsel katman üstüne biner.

### 1 — Veri + Tespit 

| ID | Task | Done-criteria (DoD) |
|---|---|---|
| T1.1 | **Erişim doğrulama** — demo DataHub'a MCP → GraphQL fallback ile bağlan | Tek bir dataset'in schema + field-tags + downstream lineage'ı JSON olarak elde edildi; auth gereksinimi netleşti |
| T1.2 | **Repo iskeleti + config + LICENSE** — python paket, `config.yaml` (datahub_url, ollama_url, model), Apache-2.0 | `python -m sentinel --help` çalışıyor; LICENSE repo kökünde |
| T1.3 | **Fetch + normalize katmanı** — dataset, field-level tag/glossary, owners, lineage edge'leri → dataclass model | `fetch.py` bir domain için normalize graph (nodes+edges) döndürüyor |
| T1.4 | **Tespit çekirdeği R1 + R2 + severity** — untagged PII propagation + ownerless sensitive; blast-radius = downstream sayısı | `findings.json` üretiliyor; fixture/gerçek veride ≥1 gerçek leak yakalanıyor |

**1 çıktısı:** LLM olmadan bile `sentinel audit` çalışıp `findings.json` üretiyor.

###  2 — Yorumlama + Çıktı + Teslim

| ID | Task | Done-criteria (DoD) |
|---|---|---|
| T2.1 | **Ollama açıklama katmanı** — her finding → düz-dil açıklama + severity gerekçesi + remediation adımı | LLM çağrıları yalnız localhost:11434; `report.md` zenginleşiyor; ağ logunda dış LLM trafiği yok |
| T2.2 | **Çıktı artefaktları** — `report.md` + `lineage_graph.html` (leak yolu kırmızı vurgulu) | İki dosya `outputs/` altında üretiliyor, tarayıcıda açılıyor |
| T2.3 | **Patch üreteci + `examples/`** — her ihlal için DataHub SDK Python snippet + YAML patch | `examples/` içinde findings.json, report.md ve ≥1 patch örneği |
| T2.4 | **README + tek komut + senaryo seçimi** — klonla→çalıştır akışı, demo için 3 net leak seç | Judge `README` adımlarıyla tek komutta raporu üretebiliyor |
| T2.5 | **Demo video + submit** — <3dk, network log ile "local" kanıtı, repo public | YouTube/Vimeo public link; Devpost submit |

**Sıra bağımlılığı:** T1.1→T1.3→T1.4 zorunlu zincir. T1.2 paralel. Gün 2'de T2.1 ve T2.2 T1.4'e bağlı; T2.3 T1.4'e bağlı; T2.4/T2.5 en son.

---

## 11. Riskler & Önlemler

| Risk | Önlem |
|---|---|
| Hosted demo GraphQL auth/token istiyor | Gün 1 doğrula; gerekirse token ile veya sample metadata dump'a düş |
| Demo katalogda yeterli PII/leak yok | Kendi sentetik lineage senaryomuzu DataHub'a mümkünse yükle, değilse fixture ile göster |
| Ollama kod/JSON kalitesi düşük | Deterministik çekirdek zaten LLM'siz çalışır; LLM sadece prose. Model config'lenebilir |
| MCP Server erişilemez | GraphQL fallback P0 olarak paralel geliştirilir |

---


