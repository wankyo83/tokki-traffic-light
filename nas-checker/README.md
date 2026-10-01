# 중앙 신호등 NAS 검사기 (Camoufox)

## transport-recovery-v5.1 변경점

- 주소 우선순위는 참조처 → 공개 중앙 주소 → 다음 번호 +1~+10입니다. 기존 정상 주소보다 오래된 후보로 되돌리지 않습니다.
- 사이트별 브라우저를 분리합니다. 현재 주소의 연결 리셋·타임아웃은 새 브라우저로 한 번 재확인하고, 루트 경로 실패 시 같은 사이트의 카테고리도 확인합니다. DNS 오류나 리셋 자체를 정상으로 판정하지 않습니다.
- 공개 중인 주소에 실제 Cloudflare 인증 요소가 확인된 경우에만 기존 주소의 보안 응답 보존 정책을 적용합니다. 새 후보는 실제 목록 검증을 통과해야 합니다.
- 각 검증 요청은 홈·재시도·카테고리 확인을 합친 전체 시간 제한을 사용하며, 새 번호 후보는 45초 제한입니다.

아래 설치 설명의 초기 구현과 달리 현재 실행 정책은 위 변경점과 `signal_nas/service.py`의 공개 `policy`가 기준입니다.

기존 `tokki-total-checker`/`tokki-total-warp`와 별개의 Docker Compose 프로젝트입니다. NAS의 일반 회선으로 Camoufox 브라우저를 열어 1시간마다 공개 `domains.json`의 현재 주소를 먼저 확인합니다. 실패할 때만 참조처(설정된 곳), 그다음 현재 주소의 +1~+10 번호를 순서대로 검증합니다. **설정된 카테고리 경로 중 하나도 확인되지 않은 후보는 게시하지 않으며, 기존 `domains.json` 주소를 유지합니다.** 검사 결과는 `status.json`에 게시되어 [중앙 신호등](https://wankyo83.github.io/tokki-traffic-light/)에 표시됩니다. Cloudflare 인증 통과는 사이트 정책과 IP 상태에 따라 달라서 보장되지 않습니다.

## 설치 전 확인

- NAS CPU가 `x86_64`/`amd64`인지 확인합니다. Compose는 `linux/amd64`로 설정되어 있습니다. ARM NAS에서는 이 이미지가 실행되지 않습니다.
- Synology Container Manager의 프로젝트 기능 또는 NAS SSH의 Docker Compose v2가 필요합니다. 첫 이미지 빌드는 Camoufox/Firefox 다운로드 때문에 오래 걸릴 수 있습니다.
- GitHub의 fine-grained personal access token을 준비합니다. 저장소 `wankyo83/tokki-traffic-light` 한 곳에 `Contents: Read and write` 권한만 부여합니다. 이 토큰은 NAS `.env`에만 둡니다. 공개 중앙 페이지에는 넣지 않습니다.
- NAS 자체 회선이 한국 IP인지 확인합니다. 이 프로젝트는 WARP 컨테이너 네트워크에 붙지 않습니다. 최초 검사에서 외부 위치가 `KR`로 확인되지 않으면 **게시하지 않습니다**.
- 현재 공개 중인 주소를 첫 실행 시 읽어 오므로 저장소에 남은 옛 주소가 다시 게시되지 않습니다. 첫 공개 JSON을 읽지 못해도 게시하지 않습니다.

## 설치

NAS의 `/volume1/docker/tokki-signal-nas` 같은 **새 폴더**에 이 `nas-checker` 폴더 내용 전체를 복사합니다. 기존 컨테이너 폴더에 덮어쓰지 않습니다.

1. `.env.example`을 같은 폴더의 `.env`로 복사합니다.
2. `.env`에서 `GITHUB_TOKEN`을 채웁니다. `ADMIN_TOKEN`은 검사 즉시 실행과 상세 진단용이며, 기존 값을 유지해도 됩니다.
3. SSH에서는 해당 폴더에서 `docker compose up -d --build`를 실행합니다. Container Manager에서는 해당 폴더와 `compose.yaml`을 새 프로젝트로 선택해 빌드/시작합니다.
4. `http://192.168.0.7:8792/health` 또는 Tailscale의 `http://100.79.100.62:8792/health`에서 `ok: true`가 보이는지 확인합니다.
5. NAS의 `/`는 검사 진행 상태를 보는 보조 화면입니다. 주소별 최종 결과는 공개 중앙 신호등에서 확인합니다.

NAS 보조 화면은 검사 단계, 현재 확인 중인 사이트, 완료 수, 마지막 게시 결과를 5초마다 갱신합니다. 수동 주소 변경 기능은 제공하지 않습니다. 검사 중 주소 목록은 마지막으로 게시된 결과입니다.

기존 설치를 업데이트할 때는 새 `nas-checker` 파일로 교체하되 NAS의 `.env`와 `data/`는 보존하고, Container Manager에서 이미지를 다시 빌드해 컨테이너를 재생성합니다. 파일만 교체하거나 컨테이너만 재시작하면 이전 코드가 계속 실행됩니다.

처음부터 공개 주소가 바뀌는 게 걱정되면 `GITHUB_TOKEN`을 비워 두고 이미지 빌드만 해 보세요. 다만 토큰이 비어 있으면 컨테이너가 시작되지 않습니다. 실제 시작 시 토큰을 넣어야 하며, 그때도 브라우저 검증 전에는 주소를 교체하지 않습니다.

## 동작과 제한

- 기본 1시간 간격. 매번 공개 `domains.json`의 현재 주소부터 확인합니다. 정상이면 그 사이트의 참조처와 번호 후보를 건너뜁니다.
- 현재 주소가 비정상이면 설정된 참조처 주소를 확인합니다. 참조처도 실패하거나 없는 경우에만 현재 번호의 +1~+10을 순차 확인하며 범위를 더 늘리지 않습니다. 모든 확인이 실패하면 기존 주소를 유지하고 각각의 실패 단계를 중앙 페이지에 표시합니다.
- 뉴토끼·토끼·SBXH·11툰·네이버 웹툰·애니라이프는 참조처 검사를 건너뜁니다. 짭툰은 잠정 중단으로 전체 검사에서 제외하며 기존 주소를 유지합니다.
- 사이트마다 같은 계열의 호스트명, Cloudflare 도전 화면 여부, 카테고리 경로를 확인합니다. 설정된 경로 **하나만** 확인되어도 통과합니다. 브랜드·로고·본문 단어의 일치는 판정 기준으로 사용하지 않습니다. 카테고리 링크가 초기 화면에 없으면 카테고리 경로를 직접 시도합니다.
- 최초 응답(`commit`) 뒤 실제 카테고리 화면 또는 Cloudflare 인증 요소가 나타날 때까지 기다립니다. 해결기는 탐색 전에 준비해 닫힌 shadow DOM을 열고, 인증 iframe과 체크박스를 재시도한 뒤 실제 카테고리 화면으로 전환됐는지 다시 확인합니다.
- 한 검사 주기에는 Camoufox 컨텍스트 하나를 순차 재사용해 Cloudflare 통과 쿠키를 유지하고, 각 페이지는 확인 직후 닫아 메모리 사용을 제한합니다. Compose의 공유 메모리는 1GB입니다.
- NAS가 `site/domains.json`과 `site/status.json`을 GitHub API로 **한 커밋에** 갱신하고, GitHub Actions는 Pages 배포만 합니다.
- 수동 주소 변경 UI/API는 이번 버전에서 제외했습니다. 참조처나 도메인 계열 자체가 바뀌는 경우에는 저장소 설정 수정이 필요합니다.
- Camoufox도 사이트·NAS 공인 IP에 따라 모든 Cloudflare 검증을 해결하지는 못합니다. 이 경우에는 `stale`로 표시하고 마지막 정상 주소를 유지하며, 다음 주기에 같은 세션 대기·재시도 절차를 다시 수행합니다.

## 점검

```sh
docker compose ps
docker compose logs -f checker
docker compose restart checker
```

로그에 `Published verified snapshot`이 나오면 GitHub Pages 배포를 확인합니다. `direct NAS exit not verified as KR`이면 회선/WARP 경로를 먼저 확인하세요. 강제로 게시하기 위해 `REQUIRE_KR_EGRESS`를 끄는 것은 권장하지 않습니다.
관리 화면의 `lastError`에 `GitHub API ... HTTP 404`가 나오면 `.env`의 `GITHUB_REPOSITORY=wankyo83/tokki-traffic-light`, `GITHUB_BRANCH=main`, 그리고 fine-grained token의 저장소 선택 및 `Contents: Read and write` 권한을 확인합니다. 토큰 값 자체는 화면 캡처나 문의에 포함하지 마세요.
`PATCH /git/ref/heads/main: HTTP 404`는 초기 배포본의 GitHub API 경로 오류입니다. `PATCH /git/refs/heads/main`을 사용하는 수정본으로 컨테이너 이미지를 재빌드해야 하며, 이 경우 NAS IP나 토큰을 변경할 필요가 없습니다.

중지하려면 `docker compose stop`을 사용합니다. `./data`에는 마지막 검사 결과가 남습니다. 이전 버전의 대기열 파일이 있더라도 새 버전은 사용하지 않습니다. `.env`와 `data`는 Git에 올리지 마세요.
