"""
게임에서 사용되는 모든 AI 프롬프트를 관리하는 모듈
"""

# 시나리오 생성 프롬프트
SCENARIO_GENERATION_PROMPT = """
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

# 질문 품질 평가 프롬프트
QUESTION_EVALUATION_PROMPT = """
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

# NPC 응답 생성 프롬프트
NPC_RESPONSE_PROMPT = """
당신은 추리 게임의 NPC '{npc_name}'입니다.

사건 정보:
- 제목: {title}
- 상황: {scenario}
- 피해자: {victim}
- 장소: {location}
- 시간: {time}

당신의 정보:
- 이름: {npc_name}
- 역할: {role}
- 성격: {personality}
- 비밀: {secret}
- 알리바이: {alibi}
- 피해자와의 관계: {relationship}

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

# 힌트 생성 프롬프트
HINT_GENERATION_PROMPT = """
사건 정보:
{scenario}
범인: {culprit}

플레이어에게 줄 힌트를 작성하세요. 범인을 직접적으로 밝히지 말고, 추리의 방향을 제시하는 간접적인 힌트를 주세요.
50자 이내로 작성하세요.
"""


def format_question_evaluation_prompt(question: str, scenario_context: str) -> str:
    """질문 품질 평가 프롬프트 생성"""
    return QUESTION_EVALUATION_PROMPT.format(
        question=question,
        scenario_context=scenario_context
    )


def format_npc_response_prompt(
    question: str,
    npc_info: dict,
    scenario: dict,
    conversation_history: str = ""
) -> str:
    """NPC 응답 생성 프롬프트 생성"""
    return NPC_RESPONSE_PROMPT.format(
        npc_name=npc_info['name'],
        title=scenario['title'],
        scenario=scenario['scenario'],
        victim=scenario['victim'],
        location=scenario['location'],
        time=scenario['time'],
        role=npc_info['role'],
        personality=npc_info['personality'],
        secret=npc_info['secret'],
        alibi=npc_info['alibi'],
        relationship=npc_info['relationship'],
        conversation_history=conversation_history,
        question=question
    )


def format_hint_generation_prompt(scenario: str, culprit: str) -> str:
    """힌트 생성 프롬프트 생성"""
    return HINT_GENERATION_PROMPT.format(
        scenario=scenario,
        culprit=culprit
    )


def build_conversation_history(previous_questions: list, max_items: int = 5) -> str:
    """이전 대화 히스토리 구성"""
    if not previous_questions:
        return ""
    
    conversation_history = "\n이전 질문들:\n"
    for i, q in enumerate(previous_questions[-max_items:], 1):
        conversation_history += f"{i}. Q: {q['question']}\n   A: {q['answer']}\n"
    
    return conversation_history


# 기본 시나리오 (LLM 생성 실패 시 사용)
DEFAULT_SCENARIO = {
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
