"""Independent/art-house cinema data including CineQ theaters.

Data sourced from indieground.kr and other public listings.
Coordinates are approximate and may need verification.
"""

data = [
    # 서울
    {"TheaterName": "KT&G 상상마당 시네마", "Region": "서울 마포구", "Latitude": 37.5572, "Longitude": 126.9236, "Type": "indie"},
    {"TheaterName": "KU시네마테크", "Region": "서울 광진구", "Latitude": 37.5432, "Longitude": 127.0759, "Type": "indie"},
    {"TheaterName": "더숲 아트시네마", "Region": "서울 노원구", "Latitude": 37.6545, "Longitude": 127.0568, "Type": "indie"},
    {"TheaterName": "서울아트시네마", "Region": "서울 중구", "Latitude": 37.5643, "Longitude": 126.9967, "Type": "indie"},
    {"TheaterName": "씨네큐 신도림", "TheaterCode": "1001", "Region": "서울 구로구", "Address": "서울특별시 구로구 새말로 97, 신도림테크노마트 12층", "Latitude": 37.5085, "Longitude": 126.8891, "Type": "cineq"},
    {"TheaterName": "씨네큐 청라", "TheaterCode": "2102", "Region": "인천 서구", "Address": "인천광역시 서구 중봉대로 610, 마루힐프라자 8층", "Latitude": 37.5282, "Longitude": 126.6605, "Type": "cineq"},
    {"TheaterName": "씨네큐 남양주다산", "TheaterCode": "2002", "Region": "경기 남양주시", "Address": "경기도 남양주시 경춘로 490, 힐스테이트지금디포레 상가동 3층", "Latitude": 37.6119, "Longitude": 127.1553, "Type": "cineq"},
    {"TheaterName": "씨네큐 천안불당", "TheaterCode": "4101", "Region": "충남 천안시", "Address": "충청남도 천안시 서북구 불당33길 28, 4층", "Latitude": 36.8200, "Longitude": 127.1100, "Type": "cineq"},
    {"TheaterName": "씨네큐 보은", "TheaterCode": "4002", "Region": "충북 보은군", "Address": "충청북도 보은군 보은읍 뱃들로 68-22, 결초보은 문화누리관", "Latitude": 36.4895, "Longitude": 127.7290, "Type": "cineq"},
    {"TheaterName": "씨네큐 전주영화의거리", "TheaterCode": "5001", "Region": "전북 전주시", "Address": "전라북도 전주시 완산구 전주객사4길 74-10", "Latitude": 35.8210, "Longitude": 127.1437, "Type": "cineq"},
    {"TheaterName": "씨네큐 경주보문", "TheaterCode": "6001", "Region": "경북 경주시", "Address": "경상북도 경주시 보문로 465-67", "Latitude": 35.8413, "Longitude": 129.2893, "Type": "cineq"},
    {"TheaterName": "씨네큐 구미봉곡", "TheaterCode": "6002", "Region": "경북 구미시", "Address": "경상북도 구미시 야은로 296", "Latitude": 36.1225, "Longitude": 128.3385, "Type": "cineq"},
    {"TheaterName": "씨네큐 칠곡호이", "TheaterCode": "6003", "Region": "경북 칠곡군", "Address": "경상북도 칠곡군 석적읍 석적로 646", "Latitude": 35.9788, "Longitude": 128.3948, "Type": "cineq"},
    {"TheaterName": "씨네큐 영덕예주", "TheaterCode": "6005", "Region": "경북 영덕군", "Address": "경상북도 영덕군 영해면 318만세길 36", "Latitude": 36.5386, "Longitude": 129.4058, "Type": "cineq"},
    {"TheaterName": "아리랑인디웨이브", "Region": "서울 성북구", "Latitude": 37.5893, "Longitude": 127.0147, "Type": "indie"},
    {"TheaterName": "아트나인", "Region": "서울 동작구", "Latitude": 37.5035, "Longitude": 126.9510, "Type": "indie"},
    {"TheaterName": "아트하우스 모모", "Region": "서울 서대문구", "Latitude": 37.5590, "Longitude": 126.9366, "Type": "indie"},
    {"TheaterName": "에무시네마", "Region": "서울 종로구", "Latitude": 37.5720, "Longitude": 126.9918, "Type": "indie"},
    {"TheaterName": "인디스페이스", "Region": "서울 마포구", "Latitude": 37.5534, "Longitude": 126.9219, "Type": "indie"},
    {"TheaterName": "필름포럼", "Region": "서울 서대문구", "Latitude": 37.5590, "Longitude": 126.9366, "Type": "indie"},
    {"TheaterName": "라이카시네마", "Region": "서울 서대문구", "Latitude": 37.5568, "Longitude": 126.9367, "Type": "indie"},
    # 경기/인천
    {"TheaterName": "판타스틱 큐브", "Region": "경기 부천시", "Latitude": 37.5044, "Longitude": 126.7660, "Type": "indie"},
    {"TheaterName": "헤이리시네마", "Region": "경기 파주시", "Latitude": 37.8354, "Longitude": 126.7089, "Type": "indie"},
    {"TheaterName": "영화공간주안", "Region": "인천 미추홀구", "Latitude": 37.4646, "Longitude": 126.6812, "Type": "indie"},
    {"TheaterName": "인천미림극장", "Region": "인천 미추홀구", "Latitude": 37.4634, "Longitude": 126.6530, "Type": "indie"},
    # 강원
    {"TheaterName": "강릉독립예술극장 신영", "Region": "강원 강릉시", "Latitude": 37.7533, "Longitude": 128.8961, "Type": "indie"},
    # 대전/충청
    {"TheaterName": "대전 아트시네마", "Region": "대전 중구", "Latitude": 36.3283, "Longitude": 127.4284, "Type": "indie"},
    {"TheaterName": "씨네인디U", "Region": "대전 유성구", "Latitude": 36.3629, "Longitude": 127.3564, "Type": "indie"},
    {"TheaterName": "인디플러스 천안", "Region": "충남 천안시", "Latitude": 36.8150, "Longitude": 127.1139, "Type": "indie"},
    # 광주/전라
    {"TheaterName": "광주극장", "Region": "광주 동구", "Latitude": 35.1467, "Longitude": 126.9170, "Type": "indie"},
    {"TheaterName": "광주독립영화관", "Region": "광주 동구", "Latitude": 35.1491, "Longitude": 126.9225, "Type": "indie"},
    {"TheaterName": "전주디지털독립영화관", "Region": "전북 전주시", "Latitude": 35.8143, "Longitude": 127.1530, "Type": "indie"},
    {"TheaterName": "시네마라운지MM", "Region": "전남 목포시", "Latitude": 34.8118, "Longitude": 126.3922, "Type": "indie"},
    # 대구/경상/부산
    {"TheaterName": "오오극장", "Region": "대구 중구", "Latitude": 35.8714, "Longitude": 128.5956, "Type": "indie"},
    {"TheaterName": "씨네아트 리좀", "Region": "경남 창원시", "Latitude": 35.2271, "Longitude": 128.6817, "Type": "indie"},
    {"TheaterName": "안동 중앙시네마", "Region": "경북 안동시", "Latitude": 36.5684, "Longitude": 128.7295, "Type": "indie"},
    {"TheaterName": "인디플러스 포항", "Region": "경북 포항시", "Latitude": 36.0190, "Longitude": 129.3435, "Type": "indie"},
    {"TheaterName": "영화의전당", "Region": "부산 해운대구", "Latitude": 35.1700, "Longitude": 129.1314, "Type": "indie"},
]
