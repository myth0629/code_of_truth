import os
import json
import uuid
import logging
from datetime import datetime, timedelta
from threading import Timer
from flask import Flask, render_template, request, jsonify, session
from dotenv import load_dotenv
import google.generativeai as genai

# 데이터베이스 모듈 import
import database as db

# 프롬프트 모듈 import
from prompts import (
    SCENARIO_GENERATION_PROMPT,
    DEFAULT_SCENARIO,
    format_question_evaluation_prompt,
    format_npc_response_prompt,
    format_hint_generation_prompt,
    build_conversation_history
)

# 로깅 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 환경 변수 로드
load_dotenv()

# Flask 앱 초기화
app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev-secret-key-change-in-production')

# 게임 설정 상수
MAX_QUESTIONS = 50  # 최대 질문 횟수
MAX_HINTS = 3  # 최대 힌트 횟수
GAME_CLEANUP_INTERVAL = 600  # 정리 간격 (초) - 10분
GAME_RETENTION_TIME = 3600  # 게임 보관 시간 (초) - 1시간

# Gemini API 설정
GEMINI_API_KEY = os.getenv('GEMINI_API_KEY')
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")

genai.configure(api_key=GEMINI_API_KEY)

# 게임 세션 저장소 (활성 세션만 인메모리)
games = {}

# Gemini 모델 설정
model = genai.GenerativeModel('gemini-2.5-flash')

# 데이터베이스 초기화
db.init_db()

def cleanup_old_games():
    """오래된 게임 세션 및 DB 데이터를 정리합니다."""
    try:
        now = datetime.now()
        to_delete = []
        
        # 인메모리 게임 세션 정리
        for session_id, game in games.items():
            if game.get('is_finished'):
                end_time_str = game.get('end_time', game.get('start_time'))
                if end_time_str:
                    try:
                        end_time = datetime.fromisoformat(end_time_str)
                        if (now - end_time).total_seconds() > GAME_RETENTION_TIME:
                            to_delete.append(session_id)
                    except (ValueError, TypeError) as e:
                        logger.warning(f"게임 세션 {session_id}의 시간 파싱 실패: {e}")
        
        for session_id in to_delete:
            del games[session_id]
            logger.info(f"인메모리 게임 세션 {session_id} 정리 완료")
        
        if to_delete:
            logger.info(f"{len(to_delete)}개의 활성 세션을 정리했습니다. 현재 활성 세션: {len(games)}개")
        
        # DB 오래된 세션 정리 (24시간 이상 된 완료 세션)
        deleted_sessions = db.delete_old_sessions(hours=24)
        if deleted_sessions > 0:
            logger.info(f"DB에서 {deleted_sessions}개의 오래된 세션 삭제")
        
        # DB 오래된 시나리오 정리 (30일 이상)
        deleted_scenarios = db.delete_old_scenarios(days=30)
        if deleted_scenarios > 0:
            logger.info(f"DB에서 {deleted_scenarios}개의 오래된 시나리오 삭제")
        
    except Exception as e:
        logger.error(f"게임 세션 정리 중 오류: {e}", exc_info=True)
    finally:
        # 다음 정리 스케줄
        Timer(GAME_CLEANUP_INTERVAL, cleanup_old_games).start()

# 앱 시작 시 정리 작업 시작
cleanup_old_games()

def get_daily_scenario():
    """일일 시나리오를 가져옵니다. DB에 없으면 새로 생성합니다."""
    today = datetime.now().date().isoformat()
    
    # DB에서 오늘 시나리오 조회
    scenario = db.get_daily_scenario(today)
    if scenario:
        logger.info(f"DB에서 일일 시나리오 로드: {today}")
        return scenario
    
    # 없으면 새로 생성
    logger.info(f"새로운 일일 시나리오 생성: {today}")
    scenario = generate_scenario()
    
    # DB에 저장
    db.save_daily_scenario(today, scenario)
    
    return scenario


def generate_scenario():
    """LLM을 사용하여 살인 사건 시나리오를 생성합니다."""
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = model.generate_content(SCENARIO_GENERATION_PROMPT)
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
            
            logging.info(f"시나리오 생성 성공 (시도 {attempt + 1}/{max_retries})")
            return scenario_data
            
        except json.JSONDecodeError as e:
            logging.warning(f"시나리오 JSON 파싱 실패 (시도 {attempt + 1}/{max_retries}): {str(e)}")
            if attempt == max_retries - 1:
                logging.error("시나리오 생성 최대 재시도 횟수 초과, 기본 시나리오 사용")
            continue
        except Exception as e:
            logging.error(f"시나리오 생성 오류 (시도 {attempt + 1}/{max_retries}): {str(e)}")
            if attempt == max_retries - 1:
                logging.error("시나리오 생성 실패, 기본 시나리오 사용")
            continue
    
    # 모든 재시도 실패 시 기본 시나리오 반환
    logging.warning("기본 시나리오 사용")
    return DEFAULT_SCENARIO

def evaluate_question_quality(question, scenario_context):
    """질문의 품질을 1-100점으로 평가합니다."""
    prompt = format_question_evaluation_prompt(question, scenario_context)
    
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
    conversation_history = build_conversation_history(previous_questions, max_items=5)
    
    prompt = format_npc_response_prompt(question, npc_info, scenario, conversation_history)
    
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
        
        # 일일 시나리오 가져오기 (DB에서 또는 새로 생성)
        scenario = get_daily_scenario()
        today = datetime.now().date().isoformat()
        
        # 게임 데이터 초기화 (인메모리)
        games[session_id] = {
            'session_id': session_id,
            'scenario': scenario,
            'scenario_date': today,
            'culprit': scenario['culprit'],
            'npcs': scenario['npcs'],
            'questions': [],  # {npc_name, question, answer, quality_score, reasoning}
            'hints_used': 0,  # 사용한 힌트 횟수
            'start_time': datetime.now().isoformat(),
            'is_finished': False
        }
        
        # DB에 게임 세션 저장
        db.create_game_session(session_id, today, scenario['culprit'])
        
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
        
        logger.info(f"새 게임 시작: {session_id}, 날짜: {today}")
        
        return jsonify({
            'success': True,
            'data': public_scenario
        })
    
    except ValueError as e:
        logging.error(f"게임 시작 중 잘못된 값: {str(e)}")
        return jsonify({
            'success': False,
            'error': '게임 시작 중 오류가 발생했습니다.'
        }), 500
    except Exception as e:
        logging.error(f"게임 시작 중 오류: {str(e)}")
        return jsonify({
            'success': False,
            'error': '게임을 시작할 수 없습니다. 잠시 후 다시 시도해주세요.'
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
        
        # 질문 횟수 제한 체크
        if len(game['questions']) >= MAX_QUESTIONS:
            logging.warning(f"세션 {session_id}: 최대 질문 횟수({MAX_QUESTIONS})에 도달했습니다.")
            return jsonify({
                'success': False,
                'error': f'최대 질문 횟수({MAX_QUESTIONS}회)에 도달했습니다. 이제 범인을 지목해주세요.'
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
        timestamp = datetime.now()
        question_record = {
            'npc_name': npc_name,
            'question': question,
            'answer': answer,
            'quality_score': evaluation['score'],
            'reasoning': evaluation['reasoning'],
            'timestamp': timestamp.isoformat()
        }
        game['questions'].append(question_record)
        
        # DB에 질문 저장
        db.save_question(
            session_id=session_id,
            npc_name=npc_name,
            question=question,
            answer=answer,
            quality_score=evaluation['score'],
            reasoning=evaluation['reasoning'],
            timestamp=timestamp
        )
        
        return jsonify({
            'success': True,
            'data': {
                'answer': answer,
                'quality_score': evaluation['score'],
                'reasoning': evaluation['reasoning'],
                'total_questions': len(game['questions'])
            }
        })
    
    except ValueError as e:
        logging.error(f"세션 {session_id}: 잘못된 입력 값 - {str(e)}")
        return jsonify({
            'success': False,
            'error': '입력 값이 올바르지 않습니다.'
        }), 400
    except KeyError as e:
        logging.error(f"세션 {session_id}: 필수 키 누락 - {str(e)}")
        return jsonify({
            'success': False,
            'error': '필수 정보가 누락되었습니다.'
        }), 400
    except Exception as e:
        logging.error(f"세션 {session_id if 'session_id' in locals() else 'unknown'}: /ask 처리 중 오류 - {str(e)}")
        return jsonify({
            'success': False,
            'error': '질문 처리 중 오류가 발생했습니다.'
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
            
            # DB에 게임 결과 저장
            db.finish_game_session(
                session_id=session_id,
                solved=True,
                accused_npc=suspect_name,
                questions_count=question_count,
                hints_used=game['hints_used'],
                score_info=score_info
            )
            
            logger.info(f"게임 성공: {session_id}, 점수: {score_info['total_score']}")
            
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
            # 오답인 경우 (게임은 계속됨)
            logger.info(f"오답: {session_id}, 지목: {suspect_name}, 실제 범인: {game['culprit']}")
            
            return jsonify({
                'success': True,
                'data': {
                    'is_correct': False,
                    'message': f'{suspect_name}은(는) 범인이 아닙니다. 다시 추리해보세요.',
                    'total_questions': len(game['questions'])
                }
            })
    
    except ValueError as e:
        logging.error(f"세션 {session_id}: 범인 지목 중 잘못된 값 - {str(e)}")
        return jsonify({
            'success': False,
            'error': '입력 값이 올바르지 않습니다.'
        }), 400
    except KeyError as e:
        logging.error(f"세션 {session_id}: 필수 키 누락 - {str(e)}")
        return jsonify({
            'success': False,
            'error': '필수 정보가 누락되었습니다.'
        }), 400
    except Exception as e:
        logging.error(f"세션 {session_id if 'session_id' in locals() else 'unknown'}: /accuse 처리 중 오류 - {str(e)}")
        return jsonify({
            'success': False,
            'error': '범인 지목 처리 중 오류가 발생했습니다.'
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
        
        # 힌트 횟수 제한 체크
        if game['hints_used'] >= MAX_HINTS:
            logging.warning(f"세션 {session_id}: 최대 힌트 횟수({MAX_HINTS})에 도달했습니다.")
            return jsonify({
                'success': False,
                'error': f'최대 힌트 횟수({MAX_HINTS}회)에 도달했습니다. 더 이상 힌트를 받을 수 없습니다.'
            }), 400
        
        # 힌트 생성
        prompt = format_hint_generation_prompt(
            game['scenario']['scenario'],
            game['culprit']
        )
        
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
        game['hints_used'] += 1  # 힌트 사용 횟수 증가
        
        logging.info(f"세션 {session_id}: 힌트 제공 ({game['hints_used']}/{MAX_HINTS})")
        
        return jsonify({
            'success': True,
            'data': {
                'hint': hint,
                'penalty': '힌트 사용으로 평균 점수가 낮아집니다.',
                'hints_remaining': MAX_HINTS - game['hints_used']
            }
        })
    
    except ValueError as e:
        logging.error(f"세션 {session_id}: 힌트 생성 중 잘못된 값 - {str(e)}")
        return jsonify({
            'success': False,
            'error': '힌트 생성 중 오류가 발생했습니다.'
        }), 500
    except Exception as e:
        logging.error(f"세션 {session_id if 'session_id' in locals() else 'unknown'}: /hint 처리 중 오류 - {str(e)}")
        return jsonify({
            'success': False,
            'error': '힌트 요청 처리 중 오류가 발생했습니다.'
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

@app.route('/stats/today', methods=['GET'])
def get_today_statistics():
    """오늘의 게임 통계"""
    try:
        today = datetime.now().date().isoformat()
        stats = db.get_today_stats(today)
        
        return jsonify({
            'success': True,
            'data': {
                'date': today,
                'stats': stats
            }
        })
    except Exception as e:
        logger.error(f"오늘 통계 조회 오류: {e}")
        return jsonify({
            'success': False,
            'error': '통계 조회 중 오류가 발생했습니다.'
        }), 500

@app.route('/stats/leaderboard', methods=['GET'])
def get_today_leaderboard():
    """오늘의 리더보드 (상위 10명)"""
    try:
        today = datetime.now().date().isoformat()
        limit = int(request.args.get('limit', 10))
        leaderboard = db.get_leaderboard(today, limit)
        
        return jsonify({
            'success': True,
            'data': {
                'date': today,
                'leaderboard': leaderboard
            }
        })
    except Exception as e:
        logger.error(f"리더보드 조회 오류: {e}")
        return jsonify({
            'success': False,
            'error': '리더보드 조회 중 오류가 발생했습니다.'
        }), 500

@app.route('/stats/total', methods=['GET'])
def get_total_statistics():
    """전체 게임 통계"""
    try:
        stats = db.get_total_stats()
        
        return jsonify({
            'success': True,
            'data': stats
        })
    except Exception as e:
        logger.error(f"전체 통계 조회 오류: {e}")
        return jsonify({
            'success': False,
            'error': '통계 조회 중 오류가 발생했습니다.'
        }), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5001))
    debug = os.getenv('FLASK_DEBUG', 'True') == 'True'
    app.run(host='0.0.0.0', port=port, debug=debug)
