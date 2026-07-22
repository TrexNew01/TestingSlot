from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import random

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Database សម្រាប់រក្សាទុក Balance តាម Telegram User ID
USER_BALANCES = {}

class SlotEngine:
    def __init__(self, bet_amount=0.10):
        self.num_reels = 5
        self.reel_height = 3
        self.bet_amount = bet_amount
        self.symbols = ['WILD', 'BONUS', 'INGOT', 'ENVELOPE', 'PIXIU', 'LION', 'FISH', 'A', 'K', 'Q', 'J_10']
        
        self.paytable = {
            'INGOT':    {5: 5.0, 4: 1.5, 3: 0.5},
            'ENVELOPE': {5: 4.0, 4: 1.2, 3: 0.4},
            'PIXIU':    {5: 3.0, 4: 1.0, 3: 0.3},
            'LION':     {5: 2.5, 4: 0.8, 3: 0.25},
            'FISH':     {5: 2.0, 4: 0.6, 3: 0.2},
            'A':        {5: 1.0, 4: 0.3, 3: 0.1},
            'K':        {5: 1.0, 4: 0.3, 3: 0.1},
            'Q':        {5: 0.8, 4: 0.2, 3: 0.08},
            'J_10':     {5: 0.6, 4: 0.2, 3: 0.05},
        }

        self.paylines = [
            [(0,1), (1,1), (2,1), (3,1), (4,1)],
            [(0,0), (1,0), (2,0), (3,0), (4,0)],
            [(0,2), (1,2), (2,2), (3,2), (4,2)],
            [(0,0), (1,1), (2,2), (3,1), (4,0)],
            [(0,2), (1,1), (2,0), (3,1), (4,2)]
        ]

    def generate_grid(self):
        weights = [0.05, 0.05, 0.08, 0.08, 0.10, 0.10, 0.12, 0.12, 0.10, 0.10, 0.10]
        return [[random.choices(self.symbols, weights=weights)[0] for _ in range(self.reel_height)] for _ in range(self.num_reels)]

    def evaluate(self, grid):
        total_win = 0.0
        for line in self.paylines:
            first_sym = grid[line[0][0]][line[0][1]]
            if first_sym == 'BONUS': continue
            
            match_count = 1
            target_sym = first_sym

            for pos in line[1:]:
                curr_sym = grid[pos[0]][pos[1]]
                if target_sym == 'WILD' and curr_sym != 'BONUS':
                    target_sym = curr_sym
                    match_count += 1
                elif curr_sym == target_sym or curr_sym == 'WILD':
                    match_count += 1
                else:
                    break

            if target_sym in self.paytable and match_count in self.paytable[target_sym]:
                total_win += self.paytable[target_sym][match_count] * (self.bet_amount / 5)

        return round(total_win, 2)

class SpinRequest(BaseModel):
    user_id: int
    username: str = "Guest"
    bet_amount: float = 0.10

class DepositRequest(BaseModel):
    user_id: int
    amount: float = 10.00

# Endpoint សម្រាប់បង្វិល Slot
@app.post("/api/spin")
async def spin_game(req: SpinRequest):
    if req.bet_amount < 0.10 or req.bet_amount > 10.00:
        raise HTTPException(status_code=400, detail="Bet ត្រូវតែនៅចន្លោះ $0.10 ដល់ $10.00")

    if req.user_id not in USER_BALANCES:
        USER_BALANCES[req.user_id] = 10.00  

    current_balance = USER_BALANCES[req.user_id]

    if current_balance < req.bet_amount:
        return {
            "status": "error",
            "message": "ប្រាក់មិនគ្រប់គ្រាន់ទេ! សូមចុចប៊ូតុង 'ដាក់ប្រាក់' (Test Mode) ដើម្បីបន្ត។",
            "balance": round(current_balance, 2)
        }

    USER_BALANCES[req.user_id] -= req.bet_amount
    engine = SlotEngine(bet_amount=req.bet_amount)
    grid = engine.generate_grid()
    win_amount = engine.evaluate(grid)

    USER_BALANCES[req.user_id] += win_amount
    new_balance = round(USER_BALANCES[req.user_id], 2)

    return {
        "status": "success",
        "grid": grid,
        "total_win": win_amount,
        "balance": new_balance
    }

# Endpoint សម្រាប់ Test ដាក់ប្រាក់
@app.post("/api/deposit")
async def test_deposit(req: DepositRequest):
    if req.user_id not in USER_BALANCES:
        USER_BALANCES[req.user_id] = 0.0
    
    USER_BALANCES[req.user_id] += req.amount
    
    return {
        "status": "success",
        "message": f"ទទួលបានជោគជ័យ! បញ្ចូល ${req.amount:.2f} ទៅក្នុងគណនី (Testing)។",
        "balance": round(USER_BALANCES[req.user_id], 2)
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)