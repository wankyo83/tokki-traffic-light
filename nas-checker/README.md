# 중앙 신호등 NAS 검사기 (Camoufox)

기존 `tokki-total-checker`/`tokki-total-warp`와 별개의 Docker Compose 프로젝트입니다. NAS의 일반 회선으로 Camoufox 브라우저를 열어 1시간마다 공개 `domains.json`의 현재 주소를 먼저 확인합니다. 실패할 때만 참조처, 그다음 현재 주소의 +1~+10 번호를 순서대로 검증합니다. **실제 사이트 이름과 기본 구조를 검증하지 못한 후보는 게시하지 않으며, 기존 `domains.json` 주소를 유지합니다.** 검사 결과는 `status.json`에 게시되어 [중앙 신호등](https://wankyo83.github.io/tokki-traffic-light/)에 표시됩니다. Cloudflare 인증 통과는 사이트 정책과 IP 상태에 따라 달라서 보장되지 않습니다.

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
- 현재 주소가 비정상이면 참조처 주소를 확인합니다. 참조처가 복구되면 검증된 새 주소를 채택합니다. 참조처도 실패할 때만 현재 번호의 +1~+10을 매번 순차 확인하며 범위를 더 늘리지 않습니다. 모든 확인이 실패하면 기존 주소를 유지하고 각각의 실패 단계를 중앙 페이지에 표시합니다. 사이트는 **순차 검사**하며 후보 URL 한 개의 Camoufox 확인은 인증 처리를 포함해 최대 20초입니다.
- 뉴토끼·토끼·SBXH의 현재 공개 주소도 그대로 유지합니다. 안내처가 복구되거나 다른 주소가 실제 사이트로 검증되면 자동 반영됩니다. 실패만으로 주소를 바꾸지 않습니다.
- 사이트마다 동일 계열의 호스트명, 브랜드 텍스트, 기본 분류 텍스트, 내부 링크를 확인합니다. Cloudflare 도전 화면은 성공으로 보지 않습니다.
- NAS가 `site/domains.json`과 `site/status.json`을 GitHub API로 **한 커밋에** 갱신하고, GitHub Actions는 Pages 배포만 합니다.
- 수동 주소 변경 UI/API는 이번 버전에서 제외했습니다. 참조처나 도메인 계열 자체가 바뀌는 경우에는 저장소 설정 수정이 필요합니다.
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

중지하려면 `docker compose stop`을 사용합니다. `./data`에는 마지막 검사 결과가 남습니다. 이전 버전의 대기열 파일이 있더라도 새 버전은 사용하지 않습니다. `.env`와 `data`는 Git에 올리지 마세요.
