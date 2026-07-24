import asyncio
import random
from datetime import date
from typing import Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import database as db_module
from database import BonusState, LeaderboardEntry, SpinStat, UserAccount, UserBadge, get_session
from telegram_auth import verify_user_id

app = FastAPI(title="Golden Dragon Fortune API")

# 🌟 កំណត់ CORS ត្រឹមត្រូវ៖ allow_origins=["*"] មិនអាចប្រើជាមួយ
# allow_credentials=True បានទេ (browser នឹង block ចោល)។
# ចាំបាច់ត្រូវកំណត់ domain ច្បាស់លាស់នៅពេល deploy ជាក់ស្តែង។
ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5500",   # VS Code Live Server (default port)
    "http://127.0.0.1:5500",   # Live Server ជួនកាលប្រើ 127.0.0.1 ជំនួស localhost
    "http://localhost:5501",
    "http://127.0.0.1:5501",
    "http://localhost:8080",
    "https://trexnew01.github.io",  # 🌟 Frontend ជាក់ស្តែង (GitHub Pages, repo T-SPIN)
    "https://t-spin-wy8g.onrender.com",  # 🌟 Frontend ជាក់ស្តែង (Render Static Site)
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    """🌟 Root path — ដើម្បីកុំឱ្យបង្ហាញ 'Not Found' ទទេ ពេលនរណាម្នាក់បើក domain ដោយផ្ទាល់
    (ឧ. ពិនិត្យមើលថា Backend Deploy ជោគជ័យឬអត់)។ នេះមិនមែនជា frontend ទេ — Frontend
    ត្រូវ Deploy ដាច់ដោយឡែក (Netlify/Vercel/GitHub Pages) ហើយហៅមកកាន់ endpoint /api/... ទាំងនេះ។
    """
    return {
        "status": "ok",
        "service": "Golden Dragon Fortune API",
        "docs": "/docs",
        "game_info": "/api/game-info",
    }

# --- ធ្នឹមអាជីវកម្មរបស់ហ្គេម (constants) ---
# ដាក់នៅ module-level ព្រោះមិនប្រែប្រួលទៅតាម request/bet_amount ទេ
# ដូច្នេះមិនចាំបាច់ស្ថាបនា engine ថ្មីរាល់ spin

SYMBOLS = ['WILD', 'BONUS', 'INGOT', 'ENVELOPE', 'PIXIU', 'LION', 'FISH', 'A', 'K', 'Q', 'J_10']

SYMBOL_WEIGHTS = [0.02, 0.02, 0.03, 0.04, 0.05, 0.05, 0.07, 0.15, 0.17, 0.20, 0.20]

PAYTABLE = {
    # 🌟 តម្លៃ payout ត្រូវបានគុណដោយ scale factor ~5.125 ពី paytable ដើម
    # ដើម្បីធ្វើឱ្យ RTP (Return To Player) ស្ថិតនៅចន្លោះ 97-98%
    # (ផ្ទៀងផ្ទាត់ដោយ Monte Carlo simulation ២ដងឯករាជ្យពីគ្នា N=300,000 និង N=400,000 → 97.0%-97.7%)
    # សមាមាត្ររវាង symbol នីមួយៗនៅតែដដែល (INGOT ឈ្នះខ្ពស់បំផុត, J_10 ទាបបំផុត)
    'INGOT':    {5: 512.54, 4: 51.25, 3: 10.25},
    'ENVELOPE': {5: 256.27, 4: 41.00, 3: 7.69},
    'PIXIU':    {5: 128.13, 4: 25.63, 3: 5.13},
    'LION':     {5: 76.88,  4: 15.38, 3: 4.10},
    'FISH':     {5: 51.25,  4: 10.25, 3: 2.56},
    'A':        {5: 15.38,  4: 4.10,  3: 1.03},
    'K':        {5: 10.25,  4: 2.56,  3: 0.77},
    'Q':        {5: 7.69,   4: 2.05,  3: 0.51},
    'J_10':     {5: 5.13,   4: 1.54,  3: 0.26},
}

PAYLINES: List[List[Tuple[int, int]]] = [
    [(0, 1), (1, 1), (2, 1), (3, 1), (4, 1)], [(0, 0), (1, 0), (2, 0), (3, 0), (4, 0)],
    [(0, 2), (1, 2), (2, 2), (3, 2), (4, 2)], [(0, 0), (1, 1), (2, 2), (3, 1), (4, 0)],
    [(0, 2), (1, 1), (2, 0), (3, 1), (4, 2)], [(0, 0), (1, 0), (2, 1), (3, 2), (4, 2)],
    [(0, 2), (1, 2), (2, 1), (3, 0), (4, 0)], [(0, 1), (1, 0), (2, 0), (3, 0), (4, 1)],
    [(0, 1), (1, 2), (2, 2), (3, 2), (4, 1)], [(0, 1), (1, 0), (2, 1), (3, 2), (4, 1)],
    [(0, 1), (1, 2), (2, 1), (3, 0), (4, 1)], [(0, 0), (1, 1), (2, 0), (3, 1), (4, 0)],
    [(0, 2), (1, 1), (2, 2), (3, 1), (4, 2)], [(0, 0), (1, 1), (2, 1), (3, 1), (4, 0)],
    [(0, 2), (1, 1), (2, 1), (3, 1), (4, 2)], [(0, 1), (1, 1), (2, 0), (3, 1), (4, 1)],
    [(0, 1), (1, 1), (2, 2), (3, 1), (4, 1)], [(0, 0), (1, 0), (2, 2), (3, 0), (4, 0)],
    [(0, 2), (1, 2), (2, 0), (3, 2), (4, 2)], [(0, 0), (1, 2), (2, 2), (3, 2), (4, 0)],
]

NUM_REELS = 5
REEL_HEIGHT = 3


class SlotEngine:
    """ម៉ាស៊ីនតូចម្តងគត់ (stateless) សម្រាប់បង្កើត grid និងគណនាការឈ្នះ។
    bet_amount ត្រូវបានបញ្ជូនចូល evaluate() ជំនួសឱ្យការស្ថាបនា instance
    ថ្មីរាល់ request ព្រោះ paytable/paylines/symbols ដូចគ្នាគ្រប់ spin។
    """

    def generate_grid(self) -> List[List[str]]:
        return [
            [random.choices(SYMBOLS, weights=SYMBOL_WEIGHTS)[0] for _ in range(REEL_HEIGHT)]
            for _ in range(NUM_REELS)
        ]

    def evaluate(self, grid: List[List[str]], bet_amount: float) -> Tuple[float, List[dict]]:
        total_win = 0.0
        winning_lines_info = []  # 🌟 ផ្ទុកទិន្នន័យខ្សែដែលឈ្នះ

        for line in PAYLINES:
            first_sym = grid[line[0][0]][line[0][1]]
            if first_sym == 'BONUS':
                continue

            match_count = 1
            target_sym = first_sym
            win_positions = [[line[0][0], line[0][1]]]  # 🌟 ចាប់យកទីតាំង (col, row)

            for pos in line[1:]:
                curr_sym = grid[pos[0]][pos[1]]
                if target_sym == 'WILD' and curr_sym != 'BONUS':
                    target_sym = curr_sym
                    match_count += 1
                    win_positions.append([pos[0], pos[1]])
                elif curr_sym == target_sym or curr_sym == 'WILD':
                    match_count += 1
                    win_positions.append([pos[0], pos[1]])
                else:
                    break

            if target_sym in PAYTABLE and match_count in PAYTABLE[target_sym]:
                base_win = PAYTABLE[target_sym][match_count]
                win_amount = base_win * bet_amount  # bet_amount គឺជា multiplier គោល ១.០០
                total_win += win_amount

                # 🌟 ភ្ជាប់ទិន្នន័យខ្សែទៅឱ្យ Frontend គូរ
                winning_lines_info.append({
                    "symbol": target_sym,
                    "amount": round(win_amount, 2),
                    "positions": win_positions,
                })

        return round(total_win, 2), winning_lines_info


def count_bonus_symbols(grid: List[List[str]]) -> int:
    """រាប់ចំនួន BONUS symbol សរុបនៅលើ grid ទាំងមូល (មិនចាំបាច់ជាប់លើ payline)។"""
    return sum(reel.count('BONUS') for reel in grid)


# Instance តែមួយ ប្រើឡើងវិញបាន ព្រោះគ្មាន state ផ្ទាល់ខ្លួន
engine = SlotEngine()

# 🌟 ទិន្នន័យទាំងអស់ (balance, streak, spin stats, bonus state, badges, leaderboard)
# ឥឡូវនេះផ្ទុកជាអចិន្ត្រៃយ៍ក្នុង SQLite តាមរយៈ database.py — មិនបាត់បង់ពេល restart ទៀតទេ។
# មើល database.py សម្រាប់ schema ពេញលេញ។

STARTING_BALANCE = 10.00
MIN_WALLET_AMOUNT = 1.00
MAX_WALLET_AMOUNT = 10_000.00
MIN_BET = 0.10
MAX_BET = 100.00

# --- 🌟 ការកំណត់សម្រាប់ការលេងប្រកបដោយទំនួលខុសត្រូវ (responsible play) ---
BREAK_REMINDER_EVERY = 50

RTP_SIMULATION_SPINS = 200_000

# --- 🌟 Free Spins ---
BONUS_TRIGGER_COUNT = 3
FREE_SPINS_AWARDED = 10
FREE_SPINS_MULTIPLIER = 2.0
FREE_SPINS_MULTIPLIER_STEP = 0.5
FREE_SPINS_MULTIPLIER_MAX = 5.0

# --- 🌟 Daily login bonus ---
DAILY_LOGIN_BONUS_AMOUNT = 0.50

# --- 🌟 Pick-a-box mini game ---
PICK_BOX_COUNT = 4
PICK_BOX_VALUE_MULTIPLIERS = [1.0, 2.0, 3.0, 5.0]

LEADERBOARD_TOP_N = 10

# --- 🌟 Achievement badges ---
BADGE_DEFINITIONS = {
    "first_win":      "ឈ្នះលើកដំបូង 🎉",
    "streak_3":       "ឈ្នះជាប់គ្នា 3 ដង 🔥",
    "streak_5":       "ឈ្នះជាប់គ្នា 5 ដង 🔥🔥",
    "first_mega_win": "MEGA WIN ដំបូង 💎",
    "first_bonus":    "Bonus Round ដំបូង 🎁",
    "high_roller":    "ភ្នាល់ Max Bet 💰",
    "half_century":   "Spin 50 ដងក្នុងថ្ងៃតែមួយ 🌟",
    "ladder_master":  "ឡើងដល់កំពូល Multiplier Ladder ⚡",
}

# =====================================================================================
# 🌟 Per-user async lock — ជំនួស global _balance_lock តែមួយ
# =====================================================================================
# ជាមួយ global lock តែមួយ, spin របស់ user A នឹងធ្វើឱ្យ spin របស់ user B ត្រូវរង់ចាំ
# ទោះបីជាមិនប៉ះពាល់ទិន្នន័យគ្នាទាល់តែសោះក៏ដោយ — ក្លាយជា bottleneck ពេលមាន concurrent user ច្រើន។
# ដំណោះស្រាយ: mapping ពី user_id -> Lock ផ្ទាល់ខ្លួន, ដូច្នេះតែ request ដែលប៉ះពាល់ user
# តែមួយប៉ុណ្ណោះទើបត្រូវរង់ចាំគ្នា។ ការបង្កើត Lock ថ្មីត្រូវការពារ race condition ដាច់ដោយឡែក
# (guard lock តូចមួយ, កាន់តែខ្លីជាង logic ធំៗខាងក្នុង spin/pick-box)។

_user_locks: Dict[int, asyncio.Lock] = {}
_locks_registry_guard = asyncio.Lock()


async def get_user_lock(user_id: int) -> asyncio.Lock:
    """ត្រឡប់ (ឬបង្កើត) asyncio.Lock ផ្ទាល់ខ្លួនសម្រាប់ user_id នេះ។"""
    lock = _user_locks.get(user_id)
    if lock is not None:
        return lock
    async with _locks_registry_guard:
        # 🌟 ពិនិត្យម្តងទៀតក្នុង guard ព្រោះ request ផ្សេងអាចបានបង្កើតរួចហើយ
        lock = _user_locks.get(user_id)
        if lock is None:
            lock = asyncio.Lock()
            _user_locks[user_id] = lock
        return lock


# =====================================================================================
# 🌟 DB helper functions — ត្រូវហៅពីក្នុង per-user lock ជានិច្ច (atomic read-modify-write)
# =====================================================================================

def _get_or_create_account(db, user_id: int) -> UserAccount:
    account = db.get(UserAccount, user_id)
    if account is None:
        account = UserAccount(user_id=user_id, balance=STARTING_BALANCE, streak=0, last_login_bonus_date=None)
        db.add(account)
        db.flush()
    return account


def _get_or_create_bonus_state(db, user_id: int) -> BonusState:
    state = db.get(BonusState, user_id)
    if state is None:
        state = BonusState(
            user_id=user_id,
            free_spins_remaining=0,
            free_spin_multiplier=1.0,
            base_bet=MIN_BET,
            pending_pick_box_json=None,
        )
        db.add(state)
        db.flush()
    return state


def _register_spin(db, user_id: int) -> SpinStat:
    """កត់ត្រា spin មួយសម្រាប់ user, reset counter ថ្មីរាល់ថ្ងៃប្តូរ។"""
    today = date.today()
    stat = db.get(SpinStat, user_id)
    if stat is None or stat.stat_date != today:
        if stat is None:
            stat = SpinStat(user_id=user_id, stat_date=today, daily_count=0)
            db.add(stat)
        else:
            stat.stat_date = today
            stat.daily_count = 0
    stat.daily_count += 1
    db.flush()
    return stat


def _register_leaderboard_win(db, user_id: int, user_name: str, win_amount: float, bet_amount: float) -> None:
    if win_amount <= 0:
        return
    today = date.today()
    multiplier = round(win_amount / bet_amount, 2) if bet_amount > 0 else 0.0
    entry = db.get(LeaderboardEntry, user_id)
    if entry is None or entry.entry_date != today or win_amount > entry.best_win:
        if entry is None:
            entry = LeaderboardEntry(user_id=user_id, entry_date=today, name=user_name or "Player",
                                      best_win=win_amount, multiplier=multiplier)
            db.add(entry)
        else:
            entry.entry_date = today
            entry.name = user_name or "Player"
            entry.best_win = win_amount
            entry.multiplier = multiplier


def _check_badges(
    db,
    user_id: int,
    win_amount: float,
    bet_amount: float,
    streak: int,
    bonus_triggered: bool,
    raw_bet_amount: float = 0.0,
    spins_today: int = 0,
    free_spin_multiplier: float = 1.0,
) -> List[dict]:
    """ត្រួតពិនិត្យ និង unlock badge ថ្មីៗ, ត្រឡប់តែ badge ដែលទើប unlock ក្នុង spin នេះ។"""
    unlocked_ids = {b.badge_id for b in db.query(UserBadge).filter(UserBadge.user_id == user_id).all()}
    newly: List[dict] = []

    def award(badge_id: str):
        if badge_id not in unlocked_ids:
            unlocked_ids.add(badge_id)
            db.add(UserBadge(user_id=user_id, badge_id=badge_id))
            newly.append({"id": badge_id, "label": BADGE_DEFINITIONS[badge_id]})

    if win_amount > 0:
        award("first_win")
    if streak >= 3:
        award("streak_3")
    if streak >= 5:
        award("streak_5")
    if raw_bet_amount >= MAX_BET:
        award("high_roller")
    if spins_today >= 50:
        award("half_century")
    if free_spin_multiplier >= FREE_SPINS_MULTIPLIER_MAX:
        award("ladder_master")
    if bet_amount > 0 and win_amount / bet_amount >= 30:
        award("first_mega_win")
    if bonus_triggered:
        award("first_bonus")

    return newly


# --- 🌟 គណនា RTP ប្រហាក់ប្រហែល (Monte Carlo) ដើម្បីបង្ហាញតម្លាភាពដល់អ្នកលេង ---
GAME_INFO: dict = {
    "game_name": "Golden Dragon Fortune",
    "status": "calculating",
    "paytable": PAYTABLE,
    "num_paylines": len(PAYLINES),
    "min_bet": MIN_BET,
    "max_bet": MAX_BET,
    "symbol_odds_percent": {
        sym: round(w / sum(SYMBOL_WEIGHTS) * 100, 2)
        for sym, w in zip(SYMBOLS, SYMBOL_WEIGHTS)
    },
    "estimated_rtp_percent": None,
}


def _simulate_rtp(spins: int) -> float:
    sim_engine = SlotEngine()
    total_win = 0.0
    bet = 1.0
    for _ in range(spins):
        grid = sim_engine.generate_grid()
        win, _ = sim_engine.evaluate(grid, bet)
        total_win += win
    return round(total_win / (spins * bet) * 100, 2)


@app.on_event("startup")
async def on_startup():
    # 🌟 បង្កើត DB tables (no-op បើមានរួច)
    db_module.init_db()
    loop = asyncio.get_event_loop()
    rtp = await loop.run_in_executor(None, _simulate_rtp, RTP_SIMULATION_SPINS)
    GAME_INFO["estimated_rtp_percent"] = rtp
    GAME_INFO["status"] = "ready"


@app.get("/api/game-info")
async def get_game_info():
    return GAME_INFO


class SpinRequest(BaseModel):
    user_id: int
    bet_amount: float = Field(default=MIN_BET, ge=MIN_BET, le=MAX_BET)
    user_name: str = Field(default="Player", max_length=32)
    # 🌟 Telegram Web App initData (raw string ជាមួយ hash) — ត្រូវការសម្រាប់ផ្ទៀងផ្ទាត់ user_id
    init_data: str = Field(default="")


class WalletRequest(BaseModel):
    user_id: int
    amount: float = Field(ge=MIN_WALLET_AMOUNT, le=MAX_WALLET_AMOUNT)
    init_data: str = Field(default="")


class PickBoxRequest(BaseModel):
    user_id: int
    box_index: int = Field(ge=0, lt=PICK_BOX_COUNT)
    init_data: str = Field(default="")


class InitDataOnly(BaseModel):
    """សម្រាប់ endpoint ដែល user_id មកពី path param រួចហើយ, ត្រូវការតែ initData សម្រាប់ផ្ទៀងផ្ទាត់។"""
    init_data: str = Field(default="")


@app.post("/api/spin")
async def spin_game(req: SpinRequest):
    # 🌟 ផ្ទៀងផ្ទាត់ថា user_id ដែលបញ្ជូនមក ត្រូវគ្នាជាមួយ Telegram session ពិត
    # (ការពារការក្លែងបន្លំ user_id ដើម្បី spin យកលុយពី account អ្នកដទៃ)
    verify_user_id(req.init_data, req.user_id)

    lock = await get_user_lock(req.user_id)
    async with lock:
        with get_session() as db:
            account = _get_or_create_account(db, req.user_id)
            bonus_state = _get_or_create_bonus_state(db, req.user_id)

            pending_pick_box = bonus_state.get_pending_pick_box()
            if pending_pick_box:
                raise HTTPException(status_code=400, detail="សូមជ្រើសរើសប្រអប់ Pick-a-box ជាមុនសិន!")

            is_free_spin = bonus_state.free_spins_remaining > 0

            if is_free_spin:
                effective_bet = bonus_state.base_bet
                multiplier = bonus_state.free_spin_multiplier
            else:
                effective_bet = req.bet_amount
                multiplier = 1.0
                if account.balance < req.bet_amount:
                    raise HTTPException(status_code=400, detail="ប្រាក់មិនគ្រប់គ្រាន់ទេ!")
                account.balance -= req.bet_amount

            grid = engine.generate_grid()
            base_win, winning_lines = engine.evaluate(grid, effective_bet)
            win_amount = round(base_win * multiplier, 2)
            if multiplier != 1.0:
                for line in winning_lines:
                    line["amount"] = round(line["amount"] * multiplier, 2)

            account.balance = round(account.balance + win_amount, 2)
            new_balance = account.balance

            # 🌟 Combo streak
            streak = account.streak + 1 if win_amount > 0 else 0
            account.streak = streak

            # 🌟 ត្រួតពិនិត្យ Free Spins trigger
            bonus_count = count_bonus_symbols(grid)
            bonus_triggered = bonus_count >= BONUS_TRIGGER_COUNT

            if is_free_spin:
                bonus_state.free_spins_remaining -= 1
                if win_amount > 0:
                    bonus_state.free_spin_multiplier = round(
                        min(bonus_state.free_spin_multiplier + FREE_SPINS_MULTIPLIER_STEP, FREE_SPINS_MULTIPLIER_MAX),
                        2,
                    )
                if bonus_state.free_spins_remaining <= 0:
                    bonus_state.free_spin_multiplier = 1.0

            if bonus_triggered:
                if not is_free_spin:
                    bonus_state.base_bet = req.bet_amount
                bonus_state.free_spins_remaining += FREE_SPINS_AWARDED
                bonus_state.free_spin_multiplier = FREE_SPINS_MULTIPLIER

                values = PICK_BOX_VALUE_MULTIPLIERS.copy()
                random.shuffle(values)
                bonus_state.set_pending_pick_box({
                    "values": values,
                    "base_bet": bonus_state.base_bet,
                    "revealed": [],
                    "picks_allowed": 1,
                })

            free_spins_remaining = bonus_state.free_spins_remaining

            spin_stat = _register_spin(db, req.user_id)
            _register_leaderboard_win(db, req.user_id, req.user_name, win_amount, effective_bet)

            new_badges = _check_badges(
                db, req.user_id, win_amount, effective_bet, streak, bonus_triggered,
                raw_bet_amount=req.bet_amount,
                spins_today=spin_stat.daily_count,
                free_spin_multiplier=bonus_state.free_spin_multiplier,
            )

            spins_today = spin_stat.daily_count
            free_spin_multiplier_out = bonus_state.free_spin_multiplier

    return {
        "status": "success",
        "grid": grid,
        "total_win": win_amount,
        "balance": new_balance,
        "winning_lines": winning_lines,
        "spins_today": spins_today,
        "take_a_break": spins_today % BREAK_REMINDER_EVERY == 0,
        "is_free_spin": is_free_spin,
        "free_spins_remaining": free_spins_remaining,
        "free_spin_multiplier": free_spin_multiplier_out if free_spins_remaining > 0 else 1.0,
        "bonus_triggered": bonus_triggered,
        "pick_box": {"count": PICK_BOX_COUNT} if bonus_triggered else None,
        "streak": streak,
        "new_badges": new_badges,
    }


@app.post("/api/pick-box")
async def pick_box(req: PickBoxRequest):
    """ជ្រើសយកប្រអប់មួយក្នុង Pick-a-box mini game ដែលទើប trigger ពី Free Spins bonus។"""
    verify_user_id(req.init_data, req.user_id)

    lock = await get_user_lock(req.user_id)
    async with lock:
        with get_session() as db:
            bonus_state = db.get(BonusState, req.user_id)
            pending = bonus_state.get_pending_pick_box() if bonus_state else None
            if not pending:
                raise HTTPException(status_code=400, detail="គ្មាន Pick-a-box សកម្មសម្រាប់អ្នកលេងនេះទេ។")
            if req.box_index in pending["revealed"]:
                raise HTTPException(status_code=400, detail="ប្រអប់នេះត្រូវបានបើករួចហើយ។")

            value_multiplier = pending["values"][req.box_index]
            win_amount = round(value_multiplier * pending["base_bet"], 2)

            account = _get_or_create_account(db, req.user_id)
            account.balance = round(account.balance + win_amount, 2)
            new_balance = account.balance

            pending["revealed"].append(req.box_index)
            finished = len(pending["revealed"]) >= pending["picks_allowed"]
            all_values = pending["values"] if finished else None
            bonus_state.set_pending_pick_box(None if finished else pending)

    return {
        "status": "success",
        "win_amount": win_amount,
        "balance": new_balance,
        "finished": finished,
        "all_values": all_values,
    }


@app.get("/api/balance/{user_id}")
async def get_balance(user_id: int):
    with get_session() as db:
        account = db.get(UserAccount, user_id)
        balance = account.balance if account else STARTING_BALANCE
    return {"user_id": user_id, "balance": round(balance, 2)}


@app.post("/api/daily-bonus/{user_id}")
async def claim_daily_bonus(user_id: int, req: InitDataOnly):
    """🌟 ផ្តល់រង្វាន់ចូលលេងលើកដំបូងប្រចាំថ្ងៃ (ម្តងក្នុងមួយថ្ងៃ ក្នុងមួយ user)។"""
    verify_user_id(req.init_data, user_id)

    lock = await get_user_lock(user_id)
    async with lock:
        with get_session() as db:
            today = date.today()
            account = _get_or_create_account(db, user_id)
            already_claimed = account.last_login_bonus_date == today
            if already_claimed:
                return {"status": "already_claimed", "amount": 0.0, "balance": round(account.balance, 2)}

            account.balance = round(account.balance + DAILY_LOGIN_BONUS_AMOUNT, 2)
            account.last_login_bonus_date = today
            new_balance = account.balance

    return {"status": "claimed", "amount": DAILY_LOGIN_BONUS_AMOUNT, "balance": new_balance}


@app.post("/api/deposit")
async def deposit(req: WalletRequest):
    """🌟 ដាក់ប្រាក់ចូល demo wallet (virtual currency, មិនមែនប្រាក់ពិត)"""
    verify_user_id(req.init_data, req.user_id)

    lock = await get_user_lock(req.user_id)
    async with lock:
        with get_session() as db:
            account = _get_or_create_account(db, req.user_id)
            account.balance = round(account.balance + req.amount, 2)
            new_balance = account.balance

    return {"status": "success", "balance": new_balance}


@app.post("/api/withdraw")
async def withdraw(req: WalletRequest):
    """🌟 ដកប្រាក់ចេញពី demo wallet (virtual currency, មិនមែនប្រាក់ពិត)"""
    verify_user_id(req.init_data, req.user_id)

    lock = await get_user_lock(req.user_id)
    async with lock:
        with get_session() as db:
            account = _get_or_create_account(db, req.user_id)
            if account.balance < req.amount:
                raise HTTPException(status_code=400, detail="សមតុល្យមិនគ្រប់គ្រាន់សម្រាប់ការដកនេះទេ!")
            account.balance = round(account.balance - req.amount, 2)
            new_balance = account.balance

    return {"status": "success", "balance": new_balance}


@app.get("/api/spin-stats/{user_id}")
async def get_spin_stats(user_id: int):
    today = date.today()
    with get_session() as db:
        stat = db.get(SpinStat, user_id)
        daily_count = stat.daily_count if stat and stat.stat_date == today else 0
        account = db.get(UserAccount, user_id)
        streak = account.streak if account else 0
        bonus_state = db.get(BonusState, user_id)
        free_spins_remaining = bonus_state.free_spins_remaining if bonus_state else 0
        free_spin_multiplier = (
            bonus_state.free_spin_multiplier if bonus_state and bonus_state.free_spins_remaining > 0 else 1.0
        )
        pending_pick_box = bool(bonus_state and bonus_state.get_pending_pick_box())

    return {
        "spins_today": daily_count,
        "streak": streak,
        "free_spins_remaining": free_spins_remaining,
        "free_spin_multiplier": free_spin_multiplier,
        "pending_pick_box": pending_pick_box,
    }


@app.get("/api/badges/{user_id}")
async def get_badges(user_id: int):
    with get_session() as db:
        rows = db.query(UserBadge).filter(UserBadge.user_id == user_id).all()
        unlocked = [b.badge_id for b in rows]
    return {
        "unlocked": [{"id": b, "label": BADGE_DEFINITIONS[b]} for b in unlocked if b in BADGE_DEFINITIONS],
        "all_badges": [{"id": b, "label": label} for b, label in BADGE_DEFINITIONS.items()],
    }


@app.get("/api/leaderboard")
async def get_leaderboard():
    """បង្ហាញ Top ការឈ្នះធំបំផុតប្រចាំថ្ងៃ (ត្រូវបាន reset រាល់ថ្ងៃប្តូរ)។"""
    today = date.today()
    with get_session() as db:
        rows = db.query(LeaderboardEntry).filter(LeaderboardEntry.entry_date == today).all()
        entries = [
            {"user_id": r.user_id, "name": r.name, "best_win": round(r.best_win, 2), "multiplier": r.multiplier}
            for r in rows
        ]
    entries.sort(key=lambda e: e["best_win"], reverse=True)
    return {"leaderboard": entries[:LEADERBOARD_TOP_N]}
    
