# 중앙 신호등 NAS 검사기 (Camoufox)

기존 `tokki-total-checker`/`tokki-total-warp`와 별개의 Docker Compose 프로젝트입니다. NAS의 일반 회선으로 Camoufox 브라우저를 열어 주소 안내처와 실제 사이트를 확인합니다. 안내처가 실패하면 현재 공개 주소, 주소의 리다이렉트, 제한된 숫자 후보를 확인합니다. **실제 사이트 이름과 기본 구조를 검증하지 못한 후보는 게시하지 않으며, 기존 `domains.json` 주소를 유지합니다.** Cloudflare 인증 통과는 사이트 정책과 IP 상태에 따라 달라서 보장되지 않습니다.

## 설치 전 확인

- NAS CPU가 `x86_64`/`amd64`인지 확인합니다. Compose는 `linux/amd64`로 설정되어 있습니다. ARM NAS에서는 이 이미지가 실행되지 않습니다.
- Synology Container Manager의 프로젝트 기능 또는 NAS SSH의 Docker Compose v2가 필요합니다. 첫 이미지 빌드는 Camoufox/Firefox 다운로드 때문에 오래 걸릴 수 있습니다.
- GitHub의 fine-grained personal access token을 준비합니다. 저장소 `wankyo83/tokki-traffic-light` 한 곳에 `Contents: Read and write` 권한만 부여합니다. 이 토큰은 NAS `.env`에만 둡니다. 공개 중앙 페이지에는 넣지 않습니다.
- NAS 자체 회선이 한국 IP인지 확인합니다. 이 프로젝트는 WARP 컨테이너 네트워크에 붙지 않습니다. 최초 검사에서 외부 위치가 `KR`로 확인되지 않으면 **게시하지 않습니다**.
- 현재 공개 중인 주소를 첫 실행 시 읽어 오므로 저장소에 남은 옛 주소가 다시 게시되지 않습니다. 첫 공개 JSON을 읽지 못해도 게시하지 않습니다.

## 설치

NAS의 `/volume1/docker/tokki-signal-nas` 같은 **새 폴더**에 이 `nas-checker` 폴더 내용 전체를 복사합니다. 기존 컨테이너 폴더에 덮어쓰지 않습니다.

1. `.env.example`을 같은 폴더의 `.env`로 복사합니다.
2. `.env`에서 `GITHUB_TOKEN`을 채웁니다. `ADMIN_TOKEN`에는 임의의 긴 비밀번호(최소 24자)를 넣습니다. 예: NAS SSH에서 `openssl rand -hex 32`로 생성. 이 값은 예시를 그대로 쓰지 말고 새로 만듭니다.
3. SSH에서는 해당 폴더에서 `docker compose up -d --build`를 실행합니다. Container Manager에서는 해당 폴더와 `compose.yaml`을 새 프로젝트로 선택해 빌드/시작합니다.
4. `http://192.168.0.7:8792/health` 또는 Tailscale의 `http://100.79.100.62:8792/health`에서 `ok: true`가 보이는지 확인합니다.
5. 관리자 화면은 같은 주소의 `/`입니다. `.env`의 `ADMIN_TOKEN`을 입력하면 현재 상태와 수동 주소 후보를 볼 수 있습니다.

관리 화면은 공개 신호등처럼 만화·웹툰/미디어 목록을 나눠 표시합니다. 검사 단계, 현재 확인 중인 사이트, 완료 수, 마지막 게시 결과를 5초마다 자동 갱신하며 이 읽기 전용 화면에는 토큰이 필요하지 않습니다. 수동 주소 변경, 전체 검사 요청, 상세 오류·대기열 확인은 접힌 **관리자 기능**에서만 토큰을 사용합니다. 검사 중 주소 목록은 새 검증 결과가 아니라 마지막으로 게시된 결과입니다.

기존 설치를 업데이트할 때는 새 `nas-checker` 파일로 교체하되 NAS의 `.env`와 `data/`는 보존하고, Container Manager에서 이미지를 다시 빌드해 컨테이너를 재생성합니다. 파일만 교체하거나 컨테이너만 재시작하면 이전 코드가 계속 실행됩니다.

처음부터 공개 주소가 바뀌는 게 걱정되면 `GITHUB_TOKEN`을 비워 두고 이미지 빌드만 해 보세요. 다만 토큰이 비어 있으면 컨테이너가 시작되지 않습니다. 실제 시작 시 토큰을 넣어야 하며, 그때도 브라우저 검증 전에는 주소를 교체하지 않습니다.

## 중앙 페이지에서 수동 주소 제출

`https://wankyo83.github.io/tokki-traffic-light/`의 관리자 수동 주소 확인 영역은 **HTTPS NAS API**가 필요합니다. Pages에서 `http://192.168.0.7:8792` 또는 `http://100.79.100.62:8792`로 직접 요청하면 브라우저의 혼합 콘텐츠 정책 때문에 차단됩니다.

Synology 역방향 프록시 예시:

- 외부: `https://wankyo.synology.me:8793`
- 내부: `http://127.0.0.1:8792` (NAS 프록시가 호스트에서 실행되는 경우)
- 인증서: `wankyo.synology.me`에 유효한 인증서
- 역방향 프록시가 LAN/이 PC에서 접근 가능하도록 설정. 가능하면 외부 공개 대신 방화벽/Tailscale로 제한.

이후 중앙 페이지의 **NAS HTTPS 관리 주소**에 그 외부 주소를 입력합니다. 관리 토큰은 브라우저 저장소에 보관하지 않습니다. HTTPS 프록시를 아직 만들지 않았다면 NAS의 로컬 관리자 화면에서 먼저 수동 후보를 제출할 수 있습니다.

## 동작과 제한

- 기본 1시간 간격. 안내처는 **매번 재확인**하므로 현재 죽어 있어도 주소 출처 설정은 지우지 않았습니다.
- 후보 검색은 알려진 도메인 패턴 안에서만 합니다. 안내처의 후보와 현재 주소가 모두 실패했을 때 다음 번호 10개를 시도하고, 모두 실패하면 다음 1시간 검사에서 그 다음 10개를 확인합니다(최대 +200 범위에서 순환). 짭툰은 과거 번호 재시작 사례 때문에 첫 회차에 `001`~`010`도 확인합니다. 사이트는 **순차 검사**하며 안내처/후보 URL 한 개의 Camoufox 확인은 인증 처리를 포함해 최대 20초입니다.
- 뉴토끼·토끼·SBXH의 현재 공개 주소도 그대로 유지합니다. 안내처가 복구되거나 다른 주소가 실제 사이트로 검증되면 자동 반영됩니다. 실패만으로 주소를 바꾸지 않습니다.
- 사이트마다 동일 계열의 호스트명, 브랜드 텍스트, 기본 분류 텍스트, 내부 링크를 확인합니다. Cloudflare 도전 화면은 성공으로 보지 않습니다.
- NAS가 `site/domains.json`과 `site/status.json`을 GitHub API로 **한 커밋에** 갱신하고, GitHub Actions는 Pages 배포만 합니다.
- 관리자 API는 인증 토큰이 필수입니다. 수동 제출은 곧바로 공개되는 게 아니라 검사 대기열에 들어갑니다. 검증 실패 시 기존 주소 유지.
- Camoufox도 모든 Cloudflare 검증을 해결하지는 못합니다. 이 경우에는 `stale`로 표시하고 마지막 정상 주소를 유지합니다.

## 점검

```sh
docker compose ps
docker compose logs -f checker
docker compose restart checker
```

로그에 `Published verified snapshot`이 나오면 GitHub Pages 배포를 확인합니다. `direct NAS exit not verified as KR`이면 회선/WARP 경로를 먼저 확인하세요. 강제로 게시하기 위해 `REQUIRE_KR_EGRESS`를 끄는 것은 권장하지 않습니다.
관리 화면의 `lastError`에 `GitHub API ... HTTP 404`가 나오면 `.env`의 `GITHUB_REPOSITORY=wankyo83/tokki-traffic-light`, `GITHUB_BRANCH=main`, 그리고 fine-grained token의 저장소 선택 및 `Contents: Read and write` 권한을 확인합니다. 토큰 값 자체는 화면 캡처나 문의에 포함하지 마세요.
`PATCH /git/ref/heads/main: HTTP 404`는 초기 배포본의 GitHub API 경로 오류입니다. `PATCH /git/refs/heads/main`을 사용하는 수정본으로 컨테이너 이미지를 재빌드해야 하며, 이 경우 NAS IP나 토큰을 변경할 필요가 없습니다.

중지하려면 `docker compose stop`을 사용합니다. `./data`에는 수동 주소 대기열과 마지막 검사 결과가 남습니다. `.env`와 `data`는 Git에 올리지 마세요.
