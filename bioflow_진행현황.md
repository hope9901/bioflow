# Bioflow 최종 정리 — 장단점 · 안정화 · LLM 통합 로드맵

**목표**: 1대 워크스테이션 + 로컬 Docker 환경에서, 다른 연구자가 손쉽게 비교유전체 분석을 돌릴 수 있는 도구.

## 사용자 모델 (두 계층)

| 계층 | 누구 | 무엇을 하는가 | 인터페이스 |
|---|---|---|---|
| **Tier A · 개발자** | bioflow 메인테너 (당신) | recipe 작성, 도구 등록, SDK 확장 | `@stage` 데코레이터 · Python SDK · tool YAML registry |
| **Tier B · 최종 연구자** | 다른 연구실의 분석 사용자 | 자기 데이터로 분석 실행, 리포트 받기 | CLI 명령 · config YAML · `bioflow llm` 도우미 (코드 작성 없음) |

이 분리가 모든 설계 결정을 지배합니다:
- `@stage` 데코레이터는 Tier A 도구 — Tier B는 안 봄
- CLI / Recipe / Config YAML 이 Tier B가 실제로 만지는 표면
- LLM 도우미는 **Tier B에게 더 가치가 큼** (코드 못 짜는 연구자가 에러 만났을 때)
- "사용자가 git commit"은 Tier A에 한정 — Tier B는 git 안 씀

---

## Part 1 · 객관적 장단점 (Dickeya 262-genome 실측 기반)

### 1.1 장점 — 실제로 작동했고 가치 있는 것

| # | 장점 | 실증 |
|---|---|---|
| 1 | **Hardware-first 호환성 필터** | 12 CPU / 64 GB Windows에서 cellranger·kraken2·starsolo 자동 incompatible 분류 — 장점 중에서 가장 차별점 |
| 2 | **YAML 25줄로 도구 추가** | CAFE5·IQ-TREE·ABRicate·MAFFT·Roary 5종을 분 단위로 등록 |
| 3 | **Sibling-container + BioContainers 우선** | DinD 회피, 빌드 0, 첫 실행에서 staphb/* 이미지가 그대로 작동 |
| 4 | **NCBI ingestion 내장** | `bioflow ncbi`로 262 GCF 게놈 1.28 GB 단일 명령 |
| 5 | **실전 검증된 견고성** | 8 커밋 동안 발견·수정한 버그 모두 회귀 테스트 보호 (192/192 pass) |
| 6 | **로컬 단일 머신 전제의 단순성** | 대몬·서비스·인증 0개. Docker만 있으면 작동 |
| 7 | **Python으로 즉시 hackable** | runner·planner·NCBI 모듈 모두 직접 수정 가능 |

### 1.2 단점 — 이 목표 안에서도 여전히 아픈 것

| # | 단점 | 우리 세션의 증거 |
|---|---|---|
| 1 | **DAG / 자동 병렬화 없음** | `ThreadPoolExecutor + DockerBackend` 패턴을 사용자가 6번 직접 짬 |
| 2 | **입력 해시 기반 캐싱 없음** | 체크포인트는 stage 단위만, 입력 변경 감지 못함 |
| 3 | **Stage chaining 하드코딩** | `_chain_artifact_params()` 290줄에 모든 파이프라인 로직 |
| 4 | **YAML vs ad-hoc script 경계 어색** | 일회성 도구도 YAML 등록해야 — `run_*.py` 8개가 SDK 밖에서 만들어짐 |
| 5 | **Auto-report 없음** | `build_report.py`를 11번 손으로 갱신 |
| 6 | **운영 함정 노출** | CRLF / cp949 / HTTP 414 모두 사용자 코드까지 도달 |
| 7 | **실시간 모니터링 부재** | 6.8h 작업을 `tail -f`로 봐야 함 |
| 8 | **재시도 / fault tolerance 없음** | 컨테이너 1건 실패 = 전체 정지 |
| 9 | **출력 검증 부재** | 192 단위 테스트는 orchestrator만 보호, 결과 정확성은 검증 안 함 |

### 1.3 무시해도 좋은 약점 (목표 밖이므로)

이 niche에선 **약점이 아닌 것들** — 추가 작업 시간을 빼앗기지 말 것:

- HPC / SLURM / 클라우드 백엔드
- 멀티유저 / 인증 / 권한
- nf-core 규모 표준 파이프라인 라이브러리
- WDL / CWL 표준 호환
- 웹 UI / Tower / Galaxy 인터페이스
- 감사 추적용 provenance 시스템

---

## Part 2 · SDK 안정화 플랜 (LLM 없이 먼저)

**원칙**: LLM을 얹기 전에 SDK가 deterministic해야 합니다. 거꾸로 하면 SDK 설계가 LLM 약점에 휘둘립니다.

### Phase 1 · 정체성 확립 (3-4주)

**목표**: "Docker 명령어 카탈로그"에서 "비교유전체 ad-hoc Python SDK"로 격상.

#### **A. `@stage` 데코레이터 (1주)**
```python
from bioflow import stage, run

@stage(image="staphb/prokka:1.14.6", cpu=2, ram_gb=4)
def annotate(genome_fna):
    return f"prokka --outdir {{out_dir}} --prefix {genome_fna.stem} {genome_fna}"

@stage(image="staphb/roary:3.13.0", depends_on=annotate)
def pangenome(gffs):
    return f"roary -p 8 -i 90 -f {{out_dir}} {' '.join(map(str, gffs))}"

run([annotate, pangenome], inputs={"genome_fna": genomes})
```
- runtime DAG 빌더가 `depends_on` 그래프 분석 → 자동 chaining
- YAML registry는 **재사용 가능한 production 도구**용으로 남기고, 일회성은 Python inline
- 우리가 이번에 만든 `run_full_pangenome.py`가 절반 길이로 줄어듭니다

#### **B. 자동 병렬화 (1주)**
```python
@stage(image="...", parallel=6)              # 동시 6개 컨테이너
@stage(image="...", parallel="auto")         # CPU 수 / cpu_per_stage
```
- 입력이 list면 자동 fan-out
- runner가 ThreadPoolExecutor를 내부에서 관리
- 우리가 6번 짠 ThreadPoolExecutor 코드가 0줄로

#### **C. 입력 해시 기반 캐싱 (1주)**
```python
@stage(image="...", cache_key="auto")        # 입력 mtime+size+sha256[:16]
```
- 입력 변경 감지 → 변경된 stage만 재실행
- `~/.bioflow/cache/<hash>/` 디렉토리에 산출물 보관
- 솔로 연구자 iter loop가 결정적으로 가속됨

#### **D. Stage chaining 분리 (1주)**
- `_chain_artifact_params()` 290줄을 폐기
- chaining이 `@stage`의 `depends_on` 그래프에서 자동 추론
- planner.py가 100줄 미만으로 줄어듦
- 새 파이프라인 = 새 Python 함수 (planner.py 수정 0)

**Phase 1 완료 시점 검증 기준**: 우리가 이번 세션에 작성한 `run_full_pangenome.py` (175줄)을 SDK 위에서 **30줄**로 재작성 가능해야 합니다.

### Phase 2 · 생활 품질 (2주)

#### **E. Auto-report 누적**
```python
report.add_section("ANI heatmap", figure=fig, table=df)
```
- stage 끝에 자동으로 `summary.html`에 섹션 추가
- 매번 build_report.py 갱신 안 해도 됨

#### **F. 운영 함정 흡수 레이어**
- `bioflow.io.write_text()` — 항상 LF (CAFE5 함정 박멸)
- `bioflow.io.read_text()` — UTF-8 fallback
- 외부 API 자동 retry + exponential back-off
- 디폴트 timeout 적용

#### **G. 재시도 / fault tolerance**
```python
@stage(retry=3, retry_on=["timeout", "OOM"], retry_with={"ram_gb": "2x"})
```
- 일시적 네트워크 / OOM 자동 retry
- 동적 리소스 증가 retry

#### **H. 실시간 진행 모니터링**
- 콘솔에서 stage별 진행 상황 ANSI 표시
- container 로그를 stage prefix와 함께 stream
- `tail -f` 안 해도 됨

### Phase 3 · 비교유전체 cookbook (1-2주)

이번 Dickeya 세션의 8개 스크립트를 정제해 `bioflow/recipes/comparative_genomics/`로:

- `download_taxon.py` — NCBI taxon → assemblies
- `pangenome.py` — Prokka + Roary 자동 chain
- `phylogeny.py` — single-copy core extract → MAFFT → IQ-TREE
- `ani_matrix.py` — FastANI all-vs-all + 시각화
- `gwas.py` — Scoary + 결과 분석
- `cafe_evolution.py` — ML tree → ultrametric → CAFE5
- `amr_vf_catalogue.py` — ABRicate × 다중 DB
- `cog_enrichment.py` — Roary + COG-2024

**Phase 3 완료 시점 검증 기준**: 신규 사용자가 다른 속(genus)에 대해 **`bioflow recipe pangenome --taxon Pectobacterium`** 한 줄로 우리가 6.8시간 한 작업을 재현할 수 있어야 합니다.

---

## Part 3 · LLM 통합 플랜 (SDK 안정화 후)

**원칙**:
1. SDK 코드 경로와 LLM 코드 경로 **완전 분리** — LLM 죽어도 SDK 작동
2. **LLM은 제안만, 절대 자동 실행 안 함**
3. **데이터는 LLM에 안 가는 게 디폴트** (단계별 opt-in)
4. **로컬 LLM 옵션 기본 제공** (Ollama)

### LLM Phase 1 · 데이터 노출 0 (1일, 디폴트 ON)

#### **L1. 용어 Q&A (`bioflow llm explain`)**
```
$ bioflow llm explain "Bonferroni correction"
$ bioflow llm explain "core gene alignment"
```
- 입력: 단어 1개. 데이터 노출 0
- 학생/신참에게 가장 즉시 가치
- 디폴트로 켜도 안전

### LLM Phase 2 · 에러 진단 (1주, 디폴트 OFF, 명시적 opt-in)

#### **L2. 에러 진단 (`--llm-diagnose`)**
Stage 실패 시:
```
[bioflow] Stage failed: prokka  exit=1
[bioflow] Asking LLM (sanitized)... ✓
[bioflow] LLM suggestion:
  → 'BSpades'는 'Bacteria'의 오타로 추정
  → 제안: prokka --kingdom Bacteria <WORKSPACE>/inputs/<FILE>.fna
[bioflow] Apply this fix and retry? [y/N/edit]
```
- **경로 자동 redaction**: `<WORKSPACE>` / `<USER>` / `<FILE>` 치환
- **사용자 명시 redact_patterns 추가 가능**
- **자동 실행 절대 금지** — y/N/edit 프롬프트 강제
- **감사 로그**: 보낸 텍스트 + 토큰 + 비용 기록

### LLM Phase 3 · 명령어 / 도구 보조 (1주, 디폴트 OFF)

#### **L3. 새 도구 등록 보조**
```
$ bioflow llm new-tool prokka
[LLM이 prokka --help 분석 → tool YAML draft 생성]
[사용자가 검토·수정·commit]
```

#### **L4. 명령어 제안**
```python
cmd = bioflow.llm.suggest_command(
    tool="prokka",
    intent="annotate paired-end E. coli assembly",
)
# 사용자가 검토 후 stage에 적용
```

### LLM Phase 4 · 인프라 (1주)

#### **L5. 로컬 LLM 백엔드 (Ollama / llama.cpp)**
```yaml
# ~/.bioflow/config.yaml
llm:
  backend: "ollama"          # anthropic | openai | ollama | disabled
  model: "qwen2.5-coder:7b"
  endpoint: "http://localhost:11434"
  redact_patterns: ["patient_\\d+", "PHI:.*"]
  daily_cost_cap_usd: 5.00
```
- 민감 환경(임상·산업 IP)에서는 클라우드 호출 0건 가능
- 7B-14B 코드 모델로도 명령어 진단·용어 정의 충분

#### **L6. 감사 + 비용 상한**
- `~/.bioflow/llm_audit.log`에 모든 LLM 호출 기록 (redacted 입력 포함)
- 일일/월간 비용 cap, 초과 시 차단
- `bioflow llm audit` 명령으로 사후 검토

### LLM 명시적 비범위 (영원히 추가 안 함)

- ❌ 분석 데이터(FASTA·matrix·결과) LLM 전송
- ❌ 자동 코드 생성 후 자동 실행
- ❌ runtime의 critical path에 LLM 의존
- ❌ scaffolding 자동화 (이건 사용자가 별도 LLM chat에서 하고 git commit)

---

## Part 4 · 통합 로드맵 (10주 분량)

| 주차 | 작업 | 산출물 |
|---|---|---|
| **1-2** | Phase 1A · `@stage` 데코레이터 | `bioflow.stage` API + 기존 도구 마이그레이션 |
| **3** | Phase 1B · 자동 병렬화 | `parallel=N` 동작, ThreadPoolExecutor 0개 |
| **4** | Phase 1C · 입력 해시 캐싱 | `~/.bioflow/cache/`, mtime+sha 검증 |
| **5** | Phase 1D · Stage chaining 분리 | `planner.py` <100 줄 |
| **6** | Phase 2 E·F · Auto-report + 운영함정 흡수 | `report.add_section`, LF write 강제 |
| **7** | Phase 2 G·H · Retry + 실시간 모니터 | ANSI 진행 표시, 자동 retry |
| **8** | Phase 3 · Cookbook 8 recipe + **CLI 노출** | `bioflow recipe pangenome --taxon X` ← Tier B 최종 연구자가 처음 만지는 표면 |
| **9** | LLM L1·L2 · 용어 Q&A + 에러 진단 | `bioflow llm explain`, `--llm-diagnose` ← **Tier B 연구자에게 가장 가치 큼** |
| **10** | LLM L3·L4·L5·L6 · 도구 등록 + 로컬 LLM + 감사 | Ollama 어댑터, audit log |

### 검증 마일스톤

- **Week 5 끝**: Dickeya 분석 8개 스크립트가 SDK 위에서 절반 길이로 재작성됨
- **Week 8 끝**: `bioflow recipe pangenome --taxon X` 한 줄로 우리가 한 6.8h 작업 재현
- **Week 10 끝**: stage 실패 시 LLM이 진단 제안, 사용자 승인으로 자동 retry

---

## Part 5 · 영원히 안 할 것 명시 (scope discipline)

이 목록을 README에 박아두고 PR로 들어와도 거절합니다:

| 거절 항목 | 이유 |
|---|---|
| HPC / SLURM / k8s 백엔드 | 목표 = 1대 머신 |
| 멀티유저 / 인증 / quota | 솔로 사용 |
| WDL / CWL / Nextflow 호환 | 외부 표준 추구 안 함 |
| 웹 UI / Tower-style 대시보드 | 정적 HTML로 충분 |
| nf-core 규모 표준 파이프라인 라이브러리 | ad-hoc이 목적 |
| GUI 빌더 | Python SDK가 더 빠름 |
| 데이터 / 결과의 LLM 전송 | 프라이버시 |
| LLM 자동 실행 | 결정성 깨짐 |

---

## Part 6 · 한 줄 비전

| bioflow = "1대 워크스테이션에서 비교유전체 ad-hoc 분석을 위한 Deterministic Python SDK + 옵셔널 프라이버시-우선 LLM 컴패니언"
| 
| SDK가 결정적이라 1년 후도 같은 결과를 냅니다. **개발자(Tier A)가 recipe를 git commit**하면 **연구자(Tier B)는 CLI 한 줄로 실행**합니다. LLM 도우미는 두 계층 모두에 작동하되, 데이터는 디폴트로 노출되지 않습니다. 둘 다 로컬에서 작동합니다.

## Part 7 · 두 계층의 일상 사용 시나리오 (목표 상태)

### Tier A · 개발자 (당신) 의 작업 흐름
```python
# bioflow/recipes/comparative_genomics/pangenome.py
from bioflow import stage, recipe

@stage(image="staphb/prokka:1.14.6", cpu=2, ram_gb=4, parallel=6)
def annotate(genome_fna):
    return f"prokka --outdir {{out_dir}} --prefix {genome_fna.stem} --kingdom Bacteria {genome_fna}"

@stage(image="staphb/roary:3.13.0", cpu=8, ram_gb=28)
def pangenome(gffs):
    return f"roary -p 8 -i 90 -f {{out_dir}} {' '.join(map(str, gffs))}"

@recipe(name="pangenome", description="Genus-wide bacterial pangenome")
def run(taxon: str, max_genomes: int = 50):
    genomes = bioflow.ncbi.download(taxon, max=max_genomes)
    gffs = annotate(genomes)
    pangenome(gffs)
```
→ git commit → 새 recipe 등록 끝.

### Tier B · 최종 연구자 의 작업 흐름
```bash
$ bioflow recipe pangenome --taxon Pectobacterium --max-genomes 50
[bioflow] Detected hardware: 16 CPU / 32 GB / Linux x86_64
[bioflow] Recipe 'pangenome' will run 2 stages on 50 genomes
[bioflow] Estimated time: ~3 hours.  Continue? [Y/n] y
[bioflow] Phase 1/2: annotate × 50 (6 parallel) ████░░░░ 22/50  ETA 1:42:00
...
[bioflow] Done.  Report: pangenome_Pectobacterium_2026-04-30/summary.html
```
스테이지 실패 시:
```bash
[bioflow] Stage failed: annotate (run 14/50)  exit=1
[bioflow] Run with --llm-diagnose for AI-suggested fix? [y/N] y
[bioflow] LLM suggestion (sanitized):
  → Genome <FILE> appears to have malformed FASTA header (missing '>')
  → Suggested: bioflow recipe pangenome --skip <FILE> ...
[bioflow] Apply this fix? [y/N/edit]
```
→ git, Python, Docker 명령어 0개 학습. CLI 한 줄.

## Part 8 · 다음 액션 제안
원하시는 진입점을 골라주세요:

- **@stage 데코레이터 prototype** (Phase 1A) — Tier A 인프라의 정체성 확립, 다른 모든 것의 토대
- **bioflow llm explain prototype** (LLM L1) — 가장 안전하고 즉시 가치, Tier B에게 직접 도움
- **Cookbook 첫 recipe `pangenome.py`** (Phase 3) — Tier B가 처음 만지는 CLI 표면
- **로드맵 자체를 ROADMAP.md로 commit** — 비전을 코드베이스에 박아두기
