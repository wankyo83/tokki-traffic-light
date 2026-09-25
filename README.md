# 토끼 중앙 신호등

확장앱은 공개 GitHub Pages의 `domains.json`에서 최신 주소를 읽습니다. 관리 화면은 같은 Pages의 `index.html`입니다.

## 현재 운영 상태 (2026-09-25)

- GitHub Actions는 `site/**`가 `main`에 반영될 때 **Pages 배포만** 수행합니다. GitHub의 10분 주소 확인, 예약 실행, 수동 검사 실행은 제거했습니다.
- 이전 GitHub 주소 검사기와 5분 보조 호출용 Cloudflare Worker는 중지·제거했습니다. 기존 공개 `domains.json`과 `status.json` 및 주소는 이 정리 과정에서 변경하지 않았습니다.
- NAS의 새 1시간 Camoufox 검사기는 [`nas-checker/README.md`](nas-checker/README.md)에 설치 방법과 함께 준비되어 있습니다. **NAS에 설치·기동되기 전에는 새 주소가 자동 게시되지 않습니다.** 기존 NAS 검사 컨테이너의 중지는 NAS 관리자가 별도로 진행합니다.
- 저장소의 `site/domains.json`·`site/status.json`은 공개 Pages 결과보다 오래된 스냅샷일 수 있습니다. Pages 작업은 UI만 변경한 커밋을 배포할 때 현재 공개 주소 스냅샷을 보존하며, NAS가 새 데이터를 게시한 커밋은 더 최신 스냅샷을 배포합니다.
- NAS 설치 전 관리 화면의 검사 시각·지연 경고는 이전 상태 파일을 표시하므로 최신 검사 상태를 뜻하지 않습니다.

주소 공개 형식은 기존 `domains.json`의 `schemaVersion`과 사이트별 키·`baseUrl`을 유지해야 기존 확장앱과 호환됩니다. `status.json`은 관리 화면용 상태입니다.
