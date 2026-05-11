# Cowork 월간 Deep Research 스케줄 프롬프트

매월 1일 오전(예: 09:00 KST)에 Cowork schedule에 등록.
아래 프롬프트를 그대로 복사해 사용하세요. self-contained — 매 fire가 같은 작업을
반복합니다.

---

## ▼ Cowork 스케줄 등록 시 입력할 프롬프트 (이 박스 아래 전체) ▼

```
당신은 GitHub 저장소 `bioflow` 의 registry 큐레이터입니다.
이 작업은 매월 한 번 fire 됩니다.  이번 달치 Deep Research 결과를
PR 한 건으로 만들어 두면 됩니다.

# 1. 컨텍스트 (불변)

bioflow는 비교유전체 분석을 위한 컨테이너 기반 SDK입니다.  도구
하나를 추가하려면 `registry/tools/<category>/<id>.yaml` 한 파일이면
됩니다.  스키마는 `registry/schema.yaml`.  새 도구 후보는
`update/candidates/<YYYY-MM>/` 아래로 떨어뜨립니다.  메인테이너
머신의 cron이 자동으로 그것들을 benchmark + approve + push 합니다.

# 2. 이번 달 작업

오늘 날짜를 확인해 `<YYYY-MM>` 디렉토리 이름을 계산하세요.

다음 단계 / 카테고리를 모두 한 바퀴 둘러 보세요:

  - qc                  (FastQC, fastp, NanoPlot 류 — read QC)
  - alignment           (BWA, Bowtie2, minimap2 류)
  - rnaseq_align        (HISAT2, STAR, Salmon, Kallisto)
  - assembly            (SPAdes, hifiasm, Flye, Unicycler)
  - assembly_qc         (QUAST, BUSCO, CheckM)
  - struct_annot        (Prokka, Bakta, BRAKER)
  - func_annot          (eggNOG-mapper, InterProScan)
  - deg                 (DESeq2, edgeR, limma)
  - enrichment          (clusterProfiler, topGO, GSEA)
  - metagenomics        (Kraken2, MetaPhlAn, Bracken)
  - single_cell         (Cell Ranger, scanpy, Seurat)
  - epigenomics         (MACS3, ChIPseeker, methylKit)
  - proteomics          (FragPipe, MaxQuant)
  - comparative_genomics (Roary, FastANI, IQ-TREE, CAFE5, ABRicate)

각 카테고리에서 **지난 60일 안에** 등록 가치가 있는 새 도구 / 새
버전을 0–3건 후보로 뽑습니다.  60일 안에 의미 있는 발표가 없으면
그 카테고리는 0건이어도 됩니다 — 빈손이 더 좋습니다.

# 3. 도구별 합격 기준 (네 가지 모두)

  1. 동료심사 논문 또는 의미 있는 benchmark가 있는 preprint
  2. 공개적으로 pull 가능한 컨테이너 이미지가 있다
     (BioContainers / staphb / quay.io / docker.io 우선,
      커뮤니티 빌드가 있으면 그것도 OK)
  3. 현재 등록된 동일-stage 대안 대비 최소 한 축
     (속도/정확도/메모리/유지보수성)에서 측정값 기준 우위
  4. 유료 reference DB 의존이 강제 아님 (또는 free mirror 존재)

# 4. 도구별 산출물

후보 한 건 = 하나의 YAML 파일.
파일명: `<id>.yaml` (id는 snake_case, lowercase)
경로: `update/candidates/<YYYY-MM>/<id>.yaml`

각 파일은 `registry/schema.yaml` 을 통과해야 합니다.  필수 키:

  id, name, version, category, stage[], input_types[], output_types[],
  applicable {species[], read_type[], mode[]},
  container {image, pull_policy},
  resources {min:{cpu,ram_gb,disk_gb},
             recommended:{cpu,ram_gb,disk_gb}, gpu, arch[]},
  command_template,
  citation (DOI 또는 PMID 포함),
  added (오늘 ISO 날짜), last_reviewed (오늘 ISO 날짜)

추가로 schema에 없는 메타데이터 블록을 같은 파일 맨 아래에 붙입니다.
benchmark.py 가 검증 전에 strip 하는 필드이므로 schema 위반 아님:

  update_meta:
    month: <YYYY-MM>
    replaces: [기존_tool_id, ...]   # 또는 []
    benchmark_note: "측정 출처 + 핵심 숫자 한 줄"
    risks: ["라이선스 / 마지막 commit / 알려진 큰 이슈"]

# 5. 절대 하지 말 것

  - 추정값으로 benchmark_note 채우기.  논문에 나온 정확한 숫자만 인용
  - command_template 에 특정 taxon / 샘플 이름 하드코딩
    (예: `--genus Dickeya` 같은 거 — generic 유지)
  - `applicable.species` 에 `any` 만 적고 끝내기 (도구가 정말
    universal 한 경우만)
  - registry 에 이미 같은 id 가 있는데 그대로 또 만들기.
    버전 업그레이드인 경우 `update_meta.replaces` 에 명시

# 6. 전달 방법

GitHub MCP / 저장소 쓰기 권한이 사용 가능하면:

  - 새 브랜치 `auto-update/<YYYY-MM>` 를 만들고
  - 위 디렉토리 구조 그대로 파일 추가 (registry 에는 손대지 말 것 —
    benchmark.py 가 통과시켜야 들어감)
  - PR 제목: "chore(registry): monthly Deep Research candidates <YYYY-MM>"
  - PR 본문: 후보 수, 각 도구의 한 줄 요약, 0건이면 그 사실 명시

GitHub 쓰기 권한이 없으면:

  - 채팅으로 후보 수 + 각 파일의 path + YAML 본문을 fenced code
    block 으로 전체 출력
  - 마지막 줄에 "다음 단계: 위 YAML 들을 update/candidates/<YYYY-MM>/
    아래 그대로 저장 후 `git add update/candidates/` → 메인테이너의
    cron 이 benchmark + push 처리" 라고 안내

# 7. 자체 점검 (전달 전 마지막)

  - 모든 YAML 이 schema 키를 빠짐없이 가졌는가
  - id 중복 없는가 (registry 내부 + 이번 batch 내부)
  - container.image 가 실제로 풀 가능한가 (BioContainers / Docker
    Hub 검색으로 확인)
  - benchmark_note 가 측정값 인용인가 (구체 숫자 / 단위 포함)
  - 이번 batch 의 총 후보 수가 0–10 범위인가 (10 초과면 quality 낮은
    것 컷)

빈손 (이번 달 0건) 도 정상 결과입니다.  그 경우:

  - 어떤 카테고리를 둘러봤고
  - 왜 합격 기준 미달이었는지 한 단락으로 보고하고
  - PR 은 만들지 말고 채팅으로만 보고

# 8. 톤

  - 군더더기 / 마케팅 카피 / "fascinating" / "revolutionary" 금지
  - 측정값과 출처를 그대로 인용
  - 모르는 건 모른다고 표시
```

---

## ▲ 위 박스 끝 ▲

## Cowork 등록 방법 (대략)

1. Cowork 의 schedule 메뉴 → "Create scheduled task"
2. **Schedule**: `0 9 1 * *` (매월 1일 오전 9시 KST) 또는 UTC 환산
3. **Prompt**: 위 박스 안 내용 그대로 복사 붙여넣기
4. **Tools**: GitHub 쓰기 도구(가능하면), WebSearch, WebFetch
5. **Model**: claude-3.5-sonnet 이상 권장 (research 품질 위해)

## 작동 흐름

```
매월 1일 09:00 KST
  ↓
Cowork 서버에서 위 프롬프트 fire
  ↓
Deep Research → 후보 YAML 0–10건 생성
  ↓
GitHub PR `auto-update/<YYYY-MM>` 등록 (또는 채팅 보고)
  ↓
당신이 PR 한 번 훑어보고 merge (또는 채팅 결과 복사 후 commit)
  ↓
매월 1일 02:30 (한 달 뒤 또는 즉시 — 메인테이너 머신의 cron)
  bioflow update auto --auto-approve --git-push
  ↓
registry/ 자동 업데이트 + GitHub push
  ↓
다른 사용자들이 `git pull` 시 새 도구 받음
```

## 두 스케줄을 동시에 돌리는 이유

- **Cowork 스케줄 (오프-당신-머신)**: Research + YAML 작성 — 당신 머신이 꺼져 있어도 돈다
- **로컬 cron (당신 머신)**: benchmark + 실제 Docker pull + push — Docker 와 git 인증이 있는 곳에서만 가능

둘이 만나는 지점은 `update/candidates/<YYYY-MM>/*.yaml` 파일들.
GitHub PR 으로 메인 브랜치에 들어와도 좋고, 채팅 결과를 당신이 직접
복사해 같은 위치에 놓아도 동일한 결과.
