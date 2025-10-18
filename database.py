"""
SQLite 데이터베이스 관리 모듈
게임 시나리오, 세션, 통계를 영구 저장합니다.
"""

import sqlite3
import json
import logging
from datetime import datetime
from contextlib import contextmanager
from typing import Optional, Dict, List, Any

logger = logging.getLogger(__name__)

DB_PATH = 'game_data.db'

@contextmanager
def get_db():
    """데이터베이스 연결 컨텍스트 매니저"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # 딕셔너리처럼 접근 가능
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    """데이터베이스 초기화 및 테이블 생성"""
    with get_db() as db:
        # 일일 시나리오 테이블
        db.execute("""
            CREATE TABLE IF NOT EXISTS daily_scenarios (
                date TEXT PRIMARY KEY,
                scenario_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 게임 세션 테이블
        db.execute("""
            CREATE TABLE IF NOT EXISTS game_sessions (
                session_id TEXT PRIMARY KEY,
                scenario_date TEXT NOT NULL,
                start_time TIMESTAMP NOT NULL,
                end_time TIMESTAMP,
                is_finished BOOLEAN DEFAULT 0,
                solved BOOLEAN DEFAULT 0,
                accused_npc TEXT,
                culprit TEXT NOT NULL,
                questions_count INTEGER DEFAULT 0,
                hints_used INTEGER DEFAULT 0,
                final_score REAL,
                quality_score REAL,
                count_score REAL,
                grade TEXT,
                avg_quality REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # 질문 히스토리 테이블
        db.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                npc_name TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                quality_score INTEGER NOT NULL,
                reasoning TEXT,
                timestamp TIMESTAMP NOT NULL,
                FOREIGN KEY (session_id) REFERENCES game_sessions(session_id) ON DELETE CASCADE
            )
        """)
        
        # 인덱스 생성
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_date 
            ON game_sessions(scenario_date)
        """)
        
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_sessions_finished 
            ON game_sessions(is_finished, end_time)
        """)
        
        db.execute("""
            CREATE INDEX IF NOT EXISTS idx_questions_session 
            ON questions(session_id)
        """)
        
        db.commit()
        logger.info("데이터베이스 초기화 완료")


# ===== 일일 시나리오 관리 =====

def get_daily_scenario(date: str) -> Optional[Dict[str, Any]]:
    """특정 날짜의 시나리오 조회"""
    with get_db() as db:
        row = db.execute(
            "SELECT scenario_json FROM daily_scenarios WHERE date = ?",
            (date,)
        ).fetchone()
        
        if row:
            return json.loads(row['scenario_json'])
        return None


def save_daily_scenario(date: str, scenario: Dict[str, Any]) -> bool:
    """일일 시나리오 저장"""
    try:
        with get_db() as db:
            db.execute(
                """INSERT OR REPLACE INTO daily_scenarios (date, scenario_json, created_at)
                   VALUES (?, ?, ?)""",
                (date, json.dumps(scenario, ensure_ascii=False), datetime.now())
            )
            db.commit()
            logger.info(f"일일 시나리오 저장 완료: {date}")
            return True
    except Exception as e:
        logger.error(f"시나리오 저장 실패: {e}")
        return False


def delete_old_scenarios(days: int = 30):
    """오래된 시나리오 삭제 (기본 30일 이상)"""
    try:
        with get_db() as db:
            deleted = db.execute(
                """DELETE FROM daily_scenarios 
                   WHERE created_at < datetime('now', '-' || ? || ' days')""",
                (days,)
            )
            db.commit()
            logger.info(f"오래된 시나리오 {deleted.rowcount}개 삭제")
            return deleted.rowcount
    except Exception as e:
        logger.error(f"시나리오 삭제 실패: {e}")
        return 0


# ===== 게임 세션 관리 =====

def create_game_session(session_id: str, scenario_date: str, culprit: str) -> bool:
    """새 게임 세션 생성"""
    try:
        with get_db() as db:
            db.execute(
                """INSERT INTO game_sessions 
                   (session_id, scenario_date, start_time, culprit)
                   VALUES (?, ?, ?, ?)""",
                (session_id, scenario_date, datetime.now(), culprit)
            )
            db.commit()
            logger.info(f"게임 세션 생성: {session_id}")
            return True
    except Exception as e:
        logger.error(f"세션 생성 실패: {e}")
        return False


def finish_game_session(
    session_id: str,
    solved: bool,
    accused_npc: str,
    questions_count: int,
    hints_used: int,
    score_info: Optional[Dict[str, Any]] = None
) -> bool:
    """게임 세션 종료 및 결과 저장"""
    try:
        with get_db() as db:
            if score_info:
                db.execute(
                    """UPDATE game_sessions 
                       SET end_time = ?, is_finished = 1, solved = ?, accused_npc = ?,
                           questions_count = ?, hints_used = ?,
                           final_score = ?, quality_score = ?, count_score = ?,
                           grade = ?, avg_quality = ?
                       WHERE session_id = ?""",
                    (
                        datetime.now(), solved, accused_npc,
                        questions_count, hints_used,
                        score_info.get('total_score'),
                        score_info.get('quality_score'),
                        score_info.get('count_score'),
                        score_info.get('grade'),
                        score_info.get('avg_quality'),
                        session_id
                    )
                )
            else:
                db.execute(
                    """UPDATE game_sessions 
                       SET end_time = ?, is_finished = 1, solved = ?, accused_npc = ?,
                           questions_count = ?, hints_used = ?
                       WHERE session_id = ?""",
                    (datetime.now(), solved, accused_npc, questions_count, hints_used, session_id)
                )
            db.commit()
            logger.info(f"게임 세션 종료: {session_id}, 정답: {solved}")
            return True
    except Exception as e:
        logger.error(f"세션 종료 실패: {e}")
        return False


def get_game_session(session_id: str) -> Optional[Dict[str, Any]]:
    """게임 세션 조회"""
    with get_db() as db:
        row = db.execute(
            "SELECT * FROM game_sessions WHERE session_id = ?",
            (session_id,)
        ).fetchone()
        
        if row:
            return dict(row)
        return None


def delete_old_sessions(hours: int = 24):
    """오래된 완료 세션 삭제"""
    try:
        with get_db() as db:
            deleted = db.execute(
                """DELETE FROM game_sessions 
                   WHERE is_finished = 1 
                   AND end_time < datetime('now', '-' || ? || ' hours')""",
                (hours,)
            )
            db.commit()
            logger.info(f"오래된 세션 {deleted.rowcount}개 삭제")
            return deleted.rowcount
    except Exception as e:
        logger.error(f"세션 삭제 실패: {e}")
        return 0


# ===== 질문 히스토리 관리 =====

def save_question(
    session_id: str,
    npc_name: str,
    question: str,
    answer: str,
    quality_score: int,
    reasoning: str,
    timestamp: datetime
) -> bool:
    """질문 저장"""
    try:
        with get_db() as db:
            db.execute(
                """INSERT INTO questions 
                   (session_id, npc_name, question, answer, quality_score, reasoning, timestamp)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (session_id, npc_name, question, answer, quality_score, reasoning, timestamp)
            )
            db.commit()
            return True
    except Exception as e:
        logger.error(f"질문 저장 실패: {e}")
        return False


def get_session_questions(session_id: str) -> List[Dict[str, Any]]:
    """세션의 모든 질문 조회"""
    with get_db() as db:
        rows = db.execute(
            """SELECT * FROM questions 
               WHERE session_id = ? 
               ORDER BY timestamp ASC""",
            (session_id,)
        ).fetchall()
        
        return [dict(row) for row in rows]


# ===== 통계 조회 =====

def get_today_stats(date: str) -> Dict[str, Any]:
    """오늘의 게임 통계"""
    with get_db() as db:
        stats = db.execute(
            """SELECT 
                COUNT(*) as total_games,
                SUM(CASE WHEN is_finished = 1 THEN 1 ELSE 0 END) as completed_games,
                SUM(CASE WHEN solved = 1 THEN 1 ELSE 0 END) as solved_games,
                AVG(CASE WHEN final_score IS NOT NULL THEN final_score END) as avg_score,
                AVG(CASE WHEN questions_count > 0 THEN questions_count END) as avg_questions,
                AVG(CASE WHEN hints_used > 0 THEN hints_used END) as avg_hints
               FROM game_sessions
               WHERE scenario_date = ?""",
            (date,)
        ).fetchone()
        
        return dict(stats) if stats else {}


def get_leaderboard(date: str, limit: int = 10) -> List[Dict[str, Any]]:
    """리더보드 조회 (높은 점수 순)"""
    with get_db() as db:
        rows = db.execute(
            """SELECT session_id, final_score, grade, questions_count, hints_used, end_time
               FROM game_sessions
               WHERE scenario_date = ? AND is_finished = 1 AND solved = 1
               ORDER BY final_score DESC, questions_count ASC
               LIMIT ?""",
            (date, limit)
        ).fetchall()
        
        return [dict(row) for row in rows]


def get_total_stats() -> Dict[str, Any]:
    """전체 통계"""
    with get_db() as db:
        stats = db.execute(
            """SELECT 
                COUNT(*) as total_games,
                SUM(CASE WHEN is_finished = 1 THEN 1 ELSE 0 END) as completed_games,
                SUM(CASE WHEN solved = 1 THEN 1 ELSE 0 END) as solved_games,
                AVG(CASE WHEN final_score IS NOT NULL THEN final_score END) as avg_score,
                COUNT(DISTINCT scenario_date) as total_days
               FROM game_sessions"""
        ).fetchone()
        
        return dict(stats) if stats else {}
