# 📰 newsMail — 매일 2회 한국어 뉴스 다이제스트

GitHub Actions가 매일 **07:00, 17:00 (KST)**에 한국·국제 주요 언론사 RSS를 수집하고,
Gemini로 카테고리별 한국어 요약을 만들어 이메일로 발송합니다.

**완전 무료** (public repo + Gemini API 무료 티어 + Gmail SMTP)

## 구성

| 구성요소 | 역할 |
|---|---|
| `fetch.py` | RSS 수집 + 최근 N시간 필터 + 중복 제거 |
| `summarize.py` | Gemini 2.5 Pro 요약 (실패 시 Flash 자동 fallback) |
| `mailer.py` | Gmail SMTP로 HTML 메일 발송 |
| `main.py` | 전체 파이프라인 |
| `config/sources.yaml` | 언론사·카테고리 설정 (자유롭게 편집 가능) |
| `.github/workflows/news-digest.yml` | cron 스케줄 |

## 카테고리 & 기본 소스

- **정치**: 연합뉴스, 한겨레, 경향신문
- **경제**: 연합뉴스, 매일경제, 한국경제, BBC Business
- **사회**: 연합뉴스, 한겨레, 경향신문
- **IT/과학**: 전자신문, ZDNet Korea, 한겨레 과학, BBC Technology
- **국제**: 연합뉴스, 한겨레, BBC World, BBC Asia

소스 추가/제거는 `config/sources.yaml` 만 편집하면 됩니다.

---

## 셋업 가이드

### 1. 이 코드를 GitHub 리포지토리에 올리기

```bash
cd D:\00.workspace\999.sandbox\newsMail
git init
git add .
git commit -m "initial commit"
git branch -M main
git remote add origin https://github.com/<your-username>/newsMail.git
git push -u origin main
```

> 💡 **public repo**로 만들면 GitHub Actions 사용량이 무제한입니다. private도 월 2,000분 무료라 충분합니다.

### 2. Gemini API 키 발급

1. https://aistudio.google.com/apikey 접속
2. `Create API Key` 클릭
3. 키 복사 (한 번만 보여줍니다)

> Gemini 2.5 Pro 무료 한도: **일 100 요청 / 분당 5 요청**
> 하루 2회 × 5개 카테고리 = 10 요청이라 여유 만점.

### 3. Gmail 앱 비밀번호 생성

⚠️ Gmail 일반 비밀번호로는 SMTP 로그인이 안 됩니다. **앱 비밀번호**가 필요합니다.

1. Google 계정 → 보안 → **2단계 인증** 활성화 (필수)
2. https://myaccount.google.com/apppasswords 접속
3. 앱 이름 (예: `newsMail`) 입력 후 생성
4. 표시된 16자리 비밀번호 복사 (공백 제외하고 입력)

### 4. GitHub Secrets 등록

리포지토리 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

| Secret 이름 | 값 |
|---|---|
| `GEMINI_API_KEY` | (2단계에서 받은 키) |
| `GMAIL_USER` | `your-email@gmail.com` |
| `GMAIL_APP_PASSWORD` | (3단계에서 받은 16자리) |
| `MAIL_RECIPIENT` | 받을 이메일 주소 (자기 자신 가능) |

### 5. 동작 확인

리포지토리 → **Actions** 탭 → `뉴스 다이제스트 발송` 워크플로 선택 → **Run workflow** 버튼 클릭
→ 몇 분 후 메일 도착 확인.

이후로는 매일 자동 발송됩니다.

---

## 시간 / 카테고리 / 소스 변경하기

### 발송 시각 바꾸기
`.github/workflows/news-digest.yml`의 `cron` 수정 (UTC 기준):
- 07:00 KST = `0 22 * * *`
- 17:00 KST = `0 8 * * *`
- 변환: KST에서 9시간 빼기

### 카테고리·소스 바꾸기
`config/sources.yaml` 편집. 형식:
```yaml
categories:
  새카테고리:
    sources:
      - name: 표시이름
        url: https://example.com/rss.xml
```

### 요약 모델 바꾸기
`summarize.py` 상단의 `PRIMARY_MODEL`, `FALLBACK_MODEL` 수정.

---

## 트러블슈팅

- **메일이 안 와요**: Actions 탭 → 실패한 run → 로그 확인. 흔한 원인: Gmail 앱 비밀번호 오타, 2단계 인증 미설정.
- **특정 RSS만 비어있어요**: 언론사가 RSS URL을 바꿨을 수 있습니다. 해당 언론사 RSS 페이지에서 새 URL 확인 후 `sources.yaml` 갱신.
- **Gemini 요청 실패**: 무료 한도 초과 시 자동으로 Flash로 fallback합니다. Flash도 실패하면 헤드라인만 발송됩니다.
- **GitHub Actions cron이 정시에 안 돌아요**: 5~15분 지연은 정상입니다 (GitHub 공식 동작).

## 로컬 테스트

```powershell
$env:GEMINI_API_KEY = "..."
$env:GMAIL_USER = "you@gmail.com"
$env:GMAIL_APP_PASSWORD = "xxxxxxxxxxxxxxxx"
$env:MAIL_RECIPIENT = "you@gmail.com"
pip install -r requirements.txt
python main.py
```
