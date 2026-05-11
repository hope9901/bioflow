# bioflow — Design Rationale & Architecture Notes

> **Audience**: maintainer + contributors who want to understand *why* bioflow
> is built the way it is.  Researchers using bioflow as a tool don't need
> anything here.

The sections below are Korean-language design notes written during the initial
build.  An English summary follows each section heading.

---

## 사용자 모델 (두 계층) · User tiers

| 계층 | 누구 | 무엇을 하는가 | 인터페이스 |
|---|---|---|---|
| **Tier A · 개발자** | bioflow 메인테너 | recipe 작성, 도구 등록, SDK 확장 | `@stage` 데코레이터 · Python SDK · tool YAML registry |
| **Tier B · 최종 연구자** | 다른 연구실의 분석 사용자 | 자기 데이터로 분석 실행, 리포트 받기 | CLI 명령 · config YAML · `bioflow llm` 도우미 |

이 분리가 모든 설계 결정을 지배합니다:
- `@stage` 데코레이터는 Tier A 도구 — Tier B는 안 봄
- CLI / Recipe / Config YAML 이 Tier B가 실제로 만지는 표면
- LLM 도우미는 **Tier B에게 더 가치가 큼** (코드 못 짜는 연구자가 에러 만났을 때)
- "사용자가 git commit"은 Tier A에 한정 — Tier B는 git 안 씀

---

## Part 1 · 객관적 장단점 (Dickeya 262-genome 실측 기반)

### 장점

| # | 장점 | 실증 |
|---|---|---|
| 1 | **Hardware-first 호환성 필터** | 12 CPU / 64 GB Windows에서 cellranger·kraken2·starsolo 자동 incompatible 분류 |
| 2 | **YAML 25줄로 도구 추가** | CAFE5·IQ-TREE·ABRicate·MAFFT·Roary 5종을 분 단위로 등록 |
| 3 | **Sibling-container + BioContainers 우선** | DinD 회피, 빌드 0, 첫 실행에서 staphb/* 이미지가 그대로 작동 |
| 4 | **NCBI ingestion 내장** | `bioflow ncbi`로 262 GCF 게놈 1.28 GB 단일 명령 |
| 5 | **실전 검증된 견고성** | 회귀 테스트로 보호됨 |
| 6 | **로컬 단일 머신 전제의 단순성** | 대몬·서비스·인증 0개 |
| 7 | **Python으로 즉시 hackable** | runner·planner·NCBI 모듈 모두 직접 수정 가능 |

### 단점 (목표 안에서 여전히 아픈 것)

| # | 단점 |
|---|---|
| 1 | 입력 해시 기반 캐싱 — phase 1C에서 해결 |
| 2 | Stage chaining 하드코딩 — `@stage(depends_on=)` 그래프로 교체 |
| 3 | Auto-report 없음 — `report.add_section` API로 해결 |
| 4 | 운영 함정(CRLF / cp949 / HTTP 414) — `bioflow.io` 레이어로 흡수 |

### 의도적 비범위 (추가 안 함)

- HPC / SLURM / k8s 백엔드
- 멀티유저 / 인증 / quota
- WDL / CWL / Nextflow 호환
- 웹 UI / Tower 대시보드
- nf-core 규모 표준 파이프라인 라이브러리
- 데이터 / 결과의 LLM 전송
- LLM 자동 실행

---

## Part 2 · SDK 설계 원칙

### @stage 데코레이터

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
- YAML registry는 **재사용 가능한 production 도구**용, 일회성은 Python inline

### 자동 병렬화

```python
@stage(image="...", parallel=6)       # 동시 6개 컨테이너
@stage(image="...", parallel="auto")  # CPU 수 / cpu_per_stage
```

### 입력 해시 기반 캐싱

```python
@stage(image="...", cache_key="auto")  # 입력 mtime+size+sha256[:16]
```

### Retry / fault tolerance

```python
@stage(retry=3, retry_on=["timeout", "OOM"], retry_with={"ram_gb": "2x"})
```

---

## Part 3 · LLM 통합 원칙

1. SDK 코드 경로와 LLM 코드 경로 **완전 분리** — LLM 죽어도 SDK 작동
2. **LLM은 제안만, 절대 자동 실행 안 함**
3. **데이터는 LLM에 안 가는 게 디폴트** (단계별 opt-in)
4. **로컬 LLM 옵션 기본 제공** (Ollama)

### LLM 기능 레벨

| 레벨 | 명령 | 데이터 노출 | 기본값 |
|---|---|---|---|
| L1 | `bioflow llm explain "<term>"` | 용어 1개 | 켜짐 (설정 후) |
| L2 | `bioflow llm diagnose` | command + stderr 2KB, **redacted** | opt-in |
| L3 | `bioflow llm new-tool` | tool `--help` 출력 | opt-in |
| L4 | `bioflow llm suggest` | tool name + intent | opt-in |
| L5 | Ollama 백엔드 | 로컬 전용 | 선택 |
| L6 | `bioflow llm audit` | 로컬 로그만 읽음 | 항상 가능 |

### LLM 명시적 비범위

- ❌ 분석 데이터(FASTA·matrix·결과) LLM 전송
- ❌ 자동 코드 생성 후 자동 실행
- ❌ runtime의 critical path에 LLM 의존

---

## Part 4 · 완료 현황 (2026-05-11 기준)

| Phase / Box | 상태 | 핵심 산출물 |
|---|---|---|
| Phase 1A `@stage` 데코레이터 | ✅ | `bioflow.sdk.Stage` |
| Phase 1B 자동 병렬화 | ✅ | `parallel="auto"`, `starmap`, `imap_unordered`, progress |
| Phase 1C 입력 해시 캐싱 | ✅ | `~/.bioflow/cache/` mtime+SHA |
| Phase 1D Stage chaining 분리 | ✅ | `@pipeline` + `depends_on` |
| Phase 2E Auto-report | ✅ | `bioflow.Report` 누적 builder |
| Phase 2F 운영 함정 흡수 | ✅ | `bioflow.io` (CRLF/UTF-8/HTTP-414/retry) |
| Phase 2G 재시도 / fault tolerance | ✅ | `@stage(retry=N, retry_with={"ram_gb":"2x"})` |
| Phase 2H 실시간 모니터링 | ✅ | `BIOFLOW_STREAM_LOGS=1` 컨테이너 로그 stream |
| Phase 3 Cookbook (8 recipe) | ✅ | download_taxon · pangenome · phylogeny · ani_matrix · gwas · cafe_evolution · amr_vf_catalogue · cog_enrichment |
| LLM L1 용어 Q&A | ✅ | `bioflow llm explain` |
| LLM L2 에러 진단 | ✅ | `bioflow llm diagnose` + 자동 redaction |
| LLM L3 도구 등록 보조 | ✅ | `bioflow llm new-tool` |
| LLM L4 명령어 제안 | ✅ | `bioflow llm suggest` |
| LLM L5 Ollama 백엔드 | ✅ | setup 위저드 + Ollama HTTP 클라이언트 |
| LLM L6 감사 + 비용 cap | ✅ | JSONL 로그 + `daily_cost_cap_usd` 사전 차단 |
| 🎁 셋업 위저드 (보너스) | ✅ | `bioflow setup` 하드웨어→모델 자동 추천 |

### 달성 측정값

- Dickeya 분석 175줄 → SDK 위 **38줄** (-78%)
- 동일 입력 재실행: 35.3분 → **0.0초** (캐시)
- 단위 테스트: **426 passed**
- 등록 도구 (YAML): **58**

---

## Part 5 · 한 줄 비전

> bioflow = "1대 워크스테이션에서 비교유전체 ad-hoc 분석을 위한 Deterministic Python SDK + 옵셔널 프라이버시-우선 LLM 컴패니언"
>
> SDK가 결정적이라 1년 후도 같은 결과를 냅니다. **개발자(Tier A)가 recipe를 git commit**하면 **연구자(Tier B)는 CLI 한 줄로 실행**합니다. LLM 도우미는 두 계층 모두에 작동하되, 데이터는 디폴트로 노출되지 않습니다.
