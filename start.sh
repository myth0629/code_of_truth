#!/bin/bash

# 진실의 코드 - 빠른 시작 스크립트

echo "🔍 진실의 코드 설치를 시작합니다..."
echo ""

# 1. Python 버전 확인
echo "1️⃣  Python 버전 확인 중..."
python_version=$(python3 --version 2>&1)
if [ $? -eq 0 ]; then
    echo "✅ $python_version"
else
    echo "❌ Python 3이 설치되어 있지 않습니다."
    echo "   https://www.python.org/downloads/ 에서 Python을 다운로드하세요."
    exit 1
fi
echo ""

# 2. 가상환경 생성
echo "2️⃣  가상환경 생성 중..."
if [ ! -d "venv" ]; then
    python3 -m venv venv
    echo "✅ 가상환경 생성 완료"
else
    echo "ℹ️  가상환경이 이미 존재합니다."
fi
echo ""

# 3. 가상환경 활성화
echo "3️⃣  가상환경 활성화 중..."
source venv/bin/activate
echo "✅ 가상환경 활성화 완료"
echo ""

# 4. 의존성 패키지 설치
echo "4️⃣  의존성 패키지 설치 중..."
pip install --upgrade pip > /dev/null 2>&1
pip install -r requirements.txt
echo "✅ 패키지 설치 완료"
echo ""

# 5. .env 파일 확인
echo "5️⃣  환경 설정 파일 확인 중..."
if [ ! -f ".env" ]; then
    cp .env.example .env
    echo "⚠️  .env 파일이 생성되었습니다."
    echo "   .env 파일을 열어 GEMINI_API_KEY를 설정하세요!"
    echo ""
    echo "📝 API 키 발급 방법:"
    echo "   1. https://aistudio.google.com/app/apikey 접속"
    echo "   2. 'Create API Key' 클릭"
    echo "   3. 생성된 키를 복사하여 .env 파일의 GEMINI_API_KEY에 붙여넣기"
    echo ""
    read -p "API 키를 설정하셨나요? (y/n): " confirm
    if [ "$confirm" != "y" ]; then
        echo ""
        echo "ℹ️  API 키를 설정한 후 다시 실행해주세요."
        exit 0
    fi
else
    echo "✅ .env 파일이 존재합니다."
fi
echo ""

# 6. API 키 확인
source .env
if [ "$GEMINI_API_KEY" = "your_api_key_here" ] || [ -z "$GEMINI_API_KEY" ]; then
    echo "⚠️  Gemini API 키가 설정되지 않았습니다."
    echo "   .env 파일을 열어 GEMINI_API_KEY를 설정하세요."
    echo ""
    exit 1
fi
echo "✅ API 키가 설정되었습니다."
echo ""

# 7. 서버 시작
echo "🚀 서버를 시작합니다..."
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "   게임 접속: http://localhost:5000"
echo "   종료: Ctrl+C"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

python app.py
