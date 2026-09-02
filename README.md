# 토끼 신호등

웹툰·만화 확장앱이 사용하는 최신 주소를 한곳에서 확인하기 위한 GitHub Pages입니다.

- Newtoki·Toki·SBXH는 `뉴토끼우회.com`의 구버전·실시간·고정 주소 링크를 각각 사용합니다.
- WFWF는 `wfwf411.com`의 새로운 주소 링크를 사용합니다.
- Blacktoon은 `blacktoonurls.com/address-collection`의 블랙툰 바로가기 링크를 사용합니다.
- Jjaptoon은 공식 텔레그램 공개 페이지에서 주소가 포함된 가장 최근 게시물을 사용합니다.
- 11toon과 Naver는 정해진 고정 주소의 접속 여부만 확인합니다.
- Goodtoon은 `goodtoon.top`의 최종 이동 주소를 사용하고, 이동한 화면에 웹툰·연재·완결 메뉴가 있는지 확인합니다.
- Newxtoon은 `뉴엑스툰주소.com`의 최신 주소 링크를 사용하고, 안내된 `/comics` 화면이 정상 작품 목록인지 확인합니다.
- 숫자 주소를 `+10` 방식으로 추측하지 않으며, 안내된 주소 외의 후보를 탐색하지 않습니다.
- 새 주소는 두 번 연속 같은 값이 확인된 뒤 최신 주소로 승격합니다.
- 주소 출처 확인이 실패하면 마지막으로 확인된 주소를 유지합니다.
- GitHub Actions가 10분 간격으로 확인하고 Git 커밋 없이 GitHub Pages에 배포합니다.

확장앱용 주소는 `domains.json`, 관리 화면 상태는 `status.json`에서 제공합니다.
