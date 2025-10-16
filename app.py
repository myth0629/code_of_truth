import os
import json
import uuid
from datetime import datetime
from flask import Flask, render_template, request, jsonify, session
from dotenv import load_dotenv
import google.generativeai as genai

# 환경 변수 로드
load_dotenv()

# Flask 앱 초기화
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production')

# Gemini API 설정
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")

genai.configure(api_key=GEMINI_API_KEY)

# 게임 세션 저장소 (인메모리)
games = {}

# Gemini 모델 설정
model = genai.GenerativeModel('gemini-2.0-flash-exp')

def generate_scenario():
    """LLM을 사용하여 살인 사건 시나리오를 생성합니다."""
    prompt = """
당신은 추리 게임의 시나리오 작가입니다. 흥미진진한 살인 사건 시나리오를 생성해주세요.

다음 형식의 JSON으로 응답해주세요:

{
    "title": "사건의 제목",
    "scenario": "사건의 배경 및 상황 설명 (200자 이내)",
    "victim": "피해자 이름",
    "location": "사건 발생 장소",
    "time": "사건 발생 시간",
    "culprit": "실제 범인의 이름",
    "npcs": [
        {
            "name": "NPC 이름",
            "role": "역할 (예: 용의자, 목격자)",
            "personality": "성격 설명",
            "secret": "숨기고 있는 진실 또는 거짓말",
            "alibi": "알리바이",
            "relationship": "피해자와의 관계"
        },
        // 3명의 NPC (범인 포함)
    ],
    "key_evidence": ["증거1", "증거2", "증거3"]
}

중요: 반드시 유효한 JSON 형식으로만 응답하세요. 다른 설명은 추가하지 마세요.
범인은 3명의 NPC 중 한 명이어야 합니다.
각 NPC는 각자의 비밀과 동기가 있어야 하며, 범인이 아닌 NPC도 의심스러운 행동이나 비밀이 있어야 합니다.
"""
    
    try:
        response = model.generate_content(prompt)
        # JSON 파싱
        text = response.text.strip()
        
        # 마크다운 코드 블록 제거
        if text.startswith('```json'):
            text = text[7:]
        elif text.startswith('```'):
            text = text[3:]
        if text.endswith('```'):
            text = text[:-3]
        
        text = text.strip()
        scenario_data = json.loads(text)
        
        # 범인이 NPC 목록에 있는지 확인
        npc_names = [npc['name'] for npc in scenario_data['npcs']]
        if scenario_data['culprit'] not in npc_names:
            # 범인이 NPC 목록에 없으면 첫 번째 NPC를 범인으로 설정
            scenario_data['culprit'] = npc_names[0]
        
        return scenario_data
    except Exception as e:
        print(f"시나리오 생성 오류: {e}")
        # 기본 시나리오 반환
        return {
            "title": "저택의 비밀",
            "scenario": "유명 사업가가 자신의 저택에서 살해당했습니다. 사건 당시 저택에는 3명이 있었습니다.",
            "victim": "김재벌",
            "location": "강남구 고급 저택",
            "time": "2025년 10월 15일 밤 11시",
            "culprit": "이비서",
            "npcs": [
                {
                    "name": "이비서",
                    "role": "용의자",
                    "personality": "냉정하고 계산적",
                    "secret": "피해자가 횡령 증거를 발견했고, 이를 숨기기 위해 살해했다",
                    "alibi": "서재에서 업무를 보고 있었다고 주장",
                    "relationship": "10년간 비서로 근무"
                },
                {
                    "name": "박자녀",
                    "role": "용의자",
                    "personality": "감정적이고 충동적",
                    "secret": "아버지와 유산 문제로 큰 다툼이 있었다",
                    "alibi": "자신의 방에서 음악을 듣고 있었다고 주장",
                    "relationship": "피해자의 딸"
                },
                {
                    "name": "최요리사",
                    "role": "목격자",
                    "personality": "소심하고 관찰력이 좋음",
                    "secret": "주방에서 이비서가 서재로 들어가는 것을 목격했지만 두려워서 말하지 못하고 있다",
                    "alibi": "주방에서 다음 날 식사를 준비하고 있었다",
                    "relationship": "5년간 요리사로 근무"
                }
            ],
            "key_evidence": [
                "서재 문손잡이에서 발견된 지문",
                "피해자의 노트북에 남겨진 횡령 증거",
                "CCTV에 찍힌 복도의 그림자"
            ]
        }

def evaluate_question_quality(question, scenario_context):
    """질문의 품질을 1-100점으로 평가합니다."""
    prompt = f"""
당신은 추리 게임의 질문 품질 평가자입니다.

사건 정보:
{scenario_context}

플레이어의 질문: "{question}"

이 질문을 다음 기준으로 평가하세요:
1. 논리성 (30점): 질문이 논리적이고 추리에 도움이 되는가?
2. 구체성 (30점): 질문이 구체적이고 명확한가?
3. 효율성 (40점): 질문이 사건 해결에 직접적으로 기여할 수 있는가?

총 100점 만점으로 평가하고, 다음 JSON 형식으로만 응답하세요:
{{
    "score": 숫자 (1-100),
    "reasoning": "평가 이유 (한 문장)"
}}

중요: 반드시 유효한 JSON 형식으로만 응답하세요.
"""
    
    try:
        response = model.generate_content(prompt)
        text = response.text.strip()
        
        # JSON 파싱
        if text.startswith('```json'):
            text = text[7:]
        elif text.startswith('```'):
            text = text[3:]
        if text.endswith('```'):
            text = text[:-3]
        
        text = text.strip()
        result = json.loads(text)
        
        # 점수가 1-100 범위 내에 있는지 확인
        score = max(1, min(100, result.get('score', 50)))
        return {
            'score': score,
            'reasoning': result.get('reasoning', '평가 완료')
        }
    except Exception as e:
        print(f"질문 평가 오류: {e}")
        return {'score': 50, 'reasoning': '평가 중 오류 발생'}

def generate_npc_response(question, npc_info, scenario, previous_questions):
    """NPC의 응답을 생성합니다. NPC는 자신의 비밀을 숨기려고 합니다."""
    
    # 이전 대화 컨텍스트 구성
    conversation_history = ""
    if previous_questions:
        conversation_history = "\n이전 질문들:\n"
        for i, q in enumerate(previous_questions[-5:], 1):  # 최근 5개만
            conversation_history += f"{i}. Q: {q['question']}\n   A: {q['answer']}\n"
    
    prompt = f"""
당신은 추리 게임의 NPC '{npc_info['name']}'입니다.

사건 정보:
- 제목: {scenario['title']}
- 상황: {scenario['scenario']}
- 피해자: {scenario['victim']}
- 장소: {scenario['location']}
- 시간: {scenario['time']}

당신의 정보:
- 이름: {npc_info['name']}
- 역할: {npc_info['role']}
- 성격: {npc_info['personality']}
- 비밀: {npc_info['secret']}
- 알리바이: {npc_info['alibi']}
- 피해자와의 관계: {npc_info['relationship']}

{conversation_history}

수사관의 질문: "{question}"

역할 연기 규칙:
1. 당신의 성격에 맞게 대답하세요
2. 비밀을 직접적으로 드러내지 마세요 (단, 날카로운 질문에는 힌트를 줄 수 있습니다)
3. 자연스럽고 사실적인 대화체로 답변하세요
4. 100자 이내로 답변하세요
5. 방어적이거나 회피적인 태도를 보일 수 있습니다
6. 진실과 거짓을 섞어서 답변하세요

답변만 작성하세요 (다른 설명 없이):
"""
    
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"NPC 응답 생성 오류: {e}")
        return "죄송합니다. 지금은 대답하기 어렵습니다."

def calculate_final_score(question_count, avg_quality_score):
    """최종 점수를 계산합니다 (100점 만점)."""
    
    # 질문 품질 점수 (50점 만점)
    quality_score = 50 * (avg_quality_score / 100)
    
    # 질문 횟수 점수 (50점 만점)
    if question_count <= 10:
        count_score = 50
    elif question_count <= 20:
        # 10회 초과 시 1회당 2.5점씩 감점
        count_score = 50 - ((question_count - 10) * 2.5)
    else:
        # 20회 초과 시 추가 감점
        count_score = max(0, 25 - ((question_count - 20) * 5))
    
    total_score = quality_score + count_score
    
    # 등급 계산
    if total_score >= 90:
        grade = "S"
    elif total_score >= 80:
        grade = "A"
    elif total_score >= 70:
        grade = "B"
    elif total_score >= 60:
        grade = "C"
    else:
        grade = "D"
    
    return {
        'total_score': round(total_score, 1),
        'quality_score': round(quality_score, 1),
        'count_score': round(count_score, 1),
        'grade': grade,
        'question_count': question_count,
        'avg_quality': round(avg_quality_score, 1)
    }

# ===== 라우트 정의 =====

@app.route('/')
def index():
    """메인 페이지"""
    return render_template('index.html')

@app.route('/start', methods=['POST'])
def start_game():
    """새 게임 시작 - 시나리오 생성"""
    try:
        # 새 세션 ID 생성
        session_id = str(uuid.uuid4())
        
        # 시나리오 생성
        scenario = generate_scenario()
        
        # 게임 데이터 초기화
        games[session_id] = {
            'session_id': session_id,
            'scenario': scenario,
            'culprit': scenario['culprit'],
            'npcs': scenario['npcs'],
            'questions': [],  # {npc_name, question, answer, quality_score, reasoning}
            'start_time': datetime.now().isoformat(),
            'is_finished': False
        }
        
        # 클라이언트에 전달할 시나리오 정보 (범인 정보 제외)
        public_scenario = {
            'session_id': session_id,
            'title': scenario['title'],
            'scenario': scenario['scenario'],
            'victim': scenario['victim'],
            'location': scenario['location'],
            'time': scenario['time'],
            'npcs': [
                {
                    'name': npc['name'],
                    'role': npc['role'],
                    'personality': npc['personality'],
                    'relationship': npc['relationship']
                }
                for npc in scenario['npcs']
            ],
            'key_evidence': scenario.get('key_evidence', [])
        }
        
        return jsonify({
            'success': True,
            'data': public_scenario
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/ask', methods=['POST'])
def ask_question():
    """NPC에게 질문하기"""
    try:
        data = request.json
        session_id = data.get('session_id')
        npc_name = data.get('npc_name')
        question = data.get('question')
        
        # 입력 검증
        if not all([session_id, npc_name, question]):
            return jsonify({
                'success': False,
                'error': '필수 정보가 누락되었습니다.'
            }), 400
        
        # 세션 확인
        if session_id not in games:
            return jsonify({
                'success': False,
                'error': '유효하지 않은 세션입니다.'
            }), 404
        
        game = games[session_id]
        
        if game['is_finished']:
            return jsonify({
                'success': False,
                'error': '이미 종료된 게임입니다.'
            }), 400
        
        # NPC 찾기
        npc_info = None
        for npc in game['npcs']:
            if npc['name'] == npc_name:
                npc_info = npc
                break
        
        if not npc_info:
            return jsonify({
                'success': False,
                'error': '존재하지 않는 NPC입니다.'
            }), 404
        
        # 질문 품질 평가
        scenario_context = f"제목: {game['scenario']['title']}\n상황: {game['scenario']['scenario']}"
        evaluation = evaluate_question_quality(question, scenario_context)
        
        # NPC 응답 생성
        answer = generate_npc_response(
            question, 
            npc_info, 
            game['scenario'],
            game['questions']
        )
        
        # 질문 기록 저장
        question_record = {
            'npc_name': npc_name,
            'question': question,
            'answer': answer,
            'quality_score': evaluation['score'],
            'reasoning': evaluation['reasoning'],
            'timestamp': datetime.now().isoformat()
        }
        game['questions'].append(question_record)
        
        return jsonify({
            'success': True,
            'data': {
                'answer': answer,
                'quality_score': evaluation['score'],
                'reasoning': evaluation['reasoning'],
                'total_questions': len(game['questions'])
            }
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/accuse', methods=['POST'])
def accuse_culprit():
    """범인 지목하기"""
    try:
        data = request.json
        session_id = data.get('session_id')
        suspect_name = data.get('suspect_name')
        
        # 입력 검증
        if not all([session_id, suspect_name]):
            return jsonify({
                'success': False,
                'error': '필수 정보가 누락되었습니다.'
            }), 400
        
        # 세션 확인
        if session_id not in games:
            return jsonify({
                'success': False,
                'error': '유효하지 않은 세션입니다.'
            }), 404
        
        game = games[session_id]
        
        if game['is_finished']:
            return jsonify({
                'success': False,
                'error': '이미 종료된 게임입니다.'
            }), 400
        
        # 정답 확인
        is_correct = suspect_name == game['culprit']
        
        if is_correct:
            # 점수 계산
            question_count = len(game['questions'])
            
            if question_count == 0:
                return jsonify({
                    'success': False,
                    'error': '최소 1개의 질문을 해야 합니다.'
                }), 400
            
            avg_quality_score = sum(q['quality_score'] for q in game['questions']) / question_count
            
            score_info = calculate_final_score(question_count, avg_quality_score)
            
            # 게임 종료
            game['is_finished'] = True
            game['end_time'] = datetime.now().isoformat()
            game['final_score'] = score_info
            
            return jsonify({
                'success': True,
                'data': {
                    'is_correct': True,
                    'culprit': game['culprit'],
                    'score': score_info,
                    'message': f'정답입니다! 범인은 {game["culprit"]}입니다.'
                }
            })
        else:
            return jsonify({
                'success': True,
                'data': {
                    'is_correct': False,
                    'message': f'{suspect_name}은(는) 범인이 아닙니다. 다시 추리해보세요.',
                    'total_questions': len(game['questions'])
                }
            })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/hint', methods=['POST'])
def get_hint():
    """힌트 요청 (점수 감점)"""
    try:
        data = request.json
        session_id = data.get('session_id')
        
        if not session_id:
            return jsonify({
                'success': False,
                'error': '세션 ID가 필요합니다.'
            }), 400
        
        if session_id not in games:
            return jsonify({
                'success': False,
                'error': '유효하지 않은 세션입니다.'
            }), 404
        
        game = games[session_id]
        
        # 힌트 생성
        prompt = f"""
사건 정보:
{game['scenario']['scenario']}
범인: {game['culprit']}

플레이어에게 줄 힌트를 작성하세요. 범인을 직접적으로 밝히지 말고, 추리의 방향을 제시하는 간접적인 힌트를 주세요.
50자 이내로 작성하세요.
"""
        
        response = model.generate_content(prompt)
        hint = response.text.strip()
        
        # 힌트 사용 기록 (질문 품질 점수 감점)
        hint_record = {
            'npc_name': 'SYSTEM',
            'question': '[힌트 요청]',
            'answer': hint,
            'quality_score': 0,  # 힌트는 0점
            'reasoning': '힌트 사용',
            'timestamp': datetime.now().isoformat()
        }
        game['questions'].append(hint_record)
        
        return jsonify({
            'success': True,
            'data': {
                'hint': hint,
                'penalty': '힌트 사용으로 평균 점수가 낮아집니다.'
            }
        })
    
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/game/<session_id>', methods=['GET'])
def get_game_state(session_id):
    """게임 상태 조회"""
    if session_id not in games:
        return jsonify({
            'success': False,
            'error': '유효하지 않은 세션입니다.'
        }), 404
    
    game = games[session_id]
    
    # 민감한 정보 제외하고 반환
    return jsonify({
        'success': True,
        'data': {
            'session_id': session_id,
            'scenario': {
                'title': game['scenario']['title'],
                'scenario': game['scenario']['scenario'],
                'victim': game['scenario']['victim'],
                'location': game['scenario']['location'],
                'time': game['scenario']['time']
            },
            'total_questions': len(game['questions']),
            'is_finished': game['is_finished'],
            'final_score': game.get('final_score')
        }
    })

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5001))
    debug = os.getenv('FLASK_DEBUG', 'True') == 'True'
    app.run(host='0.0.0.0', port=port, debug=debug)
