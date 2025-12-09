---
name: PRS Developer
description: PO Review System 전용 개발 에이전트. 일관된 코드 스타일과 프로젝트 패턴을 따릅니다.
---

# PRS Developer Agent

PO Review System 개발을 위한 통합 에이전트입니다.

## 프로젝트 구조 (변경 금지)
```
backend/
├── main.py           # 진입점 (수정 최소화)
├── core/config.py    # 설정
├── routers/          # API 엔드포인트만
└── services/         # 비즈니스 로직만

frontend/
├── *.html            # 페이지별 HTML
└── assets/           # 정적 리소스

data/                 # CSV 마스터 데이터
outputs/              # 생성된 파일
```

---

## 코드 컨벤션

### Python (Backend)

**네이밍**
- 파일/함수/변수: `snake_case`
- 클래스: `PascalCase`
- 상수: `UPPER_SNAKE_CASE`

**라우터 작성 패턴**
```python
from fastapi import APIRouter, HTTPException, UploadFile
from services.{service_name} import {function_name}

router = APIRouter(prefix="/api/{domain}", tags=["{Domain}"])

@router.post("/{action}")
async def {action}_{resource}(file: UploadFile):
    try:
        result = await {service_function}(file)
        return {"status": "success", "data": result}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
```

**서비스 작성 패턴**
```python
import pandas as pd
from typing import Optional

def process_{something}(data: dict, options: Optional[dict] = None) -> dict:
    """
    한 줄 설명.
    
    Args:
        data: 입력 데이터
        options: 선택적 옵션
    
    Returns:
        처리 결과 dict
    """
    # 구현
    return result
```

**필수 규칙**
1. 라우터에 비즈니스 로직 금지 → services로 분리
2. 모든 함수에 타입 힌트
3. try/except는 라우터에서만, 서비스는 예외를 raise
4. DataFrame 컬럼명은 명시적으로

---

### JavaScript (Frontend)

**API 호출 패턴**
```javascript
const API = 'http://localhost:8001';

async function apiCall(endpoint, options = {}) {
    try {
        const res = await fetch(`${API}${endpoint}`, options);
        if (!res.ok) throw new Error(await res.text());
        return await res.json();
    } catch (err) {
        alert(`오류: ${err.message}`);
        throw err;
    }
}

// 사용
const result = await apiCall('/api/mmd/upload', {
    method: 'POST',
    body: formData
});
```

**필수 규칙**
1. 프레임워크 도입 금지 (바닐라 유지)
2. 모든 API 호출에 에러 처리
3. 한국어 UI 텍스트

---

### HTML/CSS

- 시맨틱 태그 사용 (`<main>`, `<section>`)
- 클래스명: `kebab-case` (예: `po-upload-form`)
- 인라인 스타일 금지

---

## 자주 쓰는 패턴

### 새 API 엔드포인트 추가
1. `backend/routers/{domain}.py`에 라우터 함수 추가
2. 로직이 복잡하면 `backend/services/`에 함수 분리
3. `main.py`는 건드리지 않음 (이미 라우터 등록됨)

### 새 서비스 함수 추가
1. 관련 서비스 파일에 함수 추가
2. 단일 책임 유지 (한 함수 = 한 가지 일)
3. 타입 힌트 + docstring 필수

### Excel 출력 추가
```python
from openpyxl import Workbook

def generate_report(data: list[dict], output_path: str) -> str:
    wb = Workbook()
    ws = wb.active
    # 헤더
    ws.append(list(data[0].keys()))
    # 데이터
    for row in data:
        ws.append(list(row.values()))
    wb.save(output_path)
    return output_path
```

### Firebase 저장
```python
from services.firebase_service import firebase

await firebase.save('collection_name', doc_id, data_dict)
```

---

## 금지 사항
- `serviceAccountKey.json` 커밋
- `main.py` 구조 변경
- 새 Python 패키지 임의 추가 (requirements.txt 협의 필요)
- Frontend 프레임워크 도입
- 영어/한국어 혼용 변수명

---

## 버전 관리
변경 시 `CHANGELOG.md`에 기록:
```markdown
## [x.x.x] - YYYY-MM-DD
### Added/Changed/Fixed
- 변경 내용
```
