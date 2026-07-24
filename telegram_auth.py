"""
ការផ្ទៀងផ្ទាត់ Telegram Web App initData
=========================================
បញ្ហាដែលដោះស្រាយ: មុននេះ Frontend បញ្ជូនតែ user_id ធម្មតា (លេខសុទ្ធ) ទៅ Backend ។
នរណាម្នាក់អាចបើក DevTools ហើយផ្លាស់ប្តូរ user_id ក្នុង request payload ដើម្បី
Spin ដក/បូកលុយពី account របស់អ្នកដទៃបាន ព្រោះ Backend មិនដឹងថា user_id នោះ
មែនជារបស់អ្នកកំពុងហៅ request ពិតឬអត់។

ដំណោះស្រាយ: Telegram Web App ផ្តល់ជូន `initData` (query-string like) ដែលមាន hash
ចុះហត្ថលេខាដោយ Telegram ដោយប្រើ Bot Token របស់យើង។ Backend ត្រូវគណនា hash
ឡើងវិញ ហើយប្រៀបធៀបជាមួយ hash ដែលភ្ជាប់មកជាមួយ។ បើផ្គូផ្គង -> initData ពិតជាមក
ពី Telegram មិនមែនក្លែងបន្លំទេ, ហើយយើងទាញយក user_id ពី initData នេះជំនួសការ
ជឿលើ user_id ដែល client ផ្ញើមកផ្ទាល់។

មើលឯកសារពាក់ព័ន្ធ៖ https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
"""
import hashlib
import hmac
import json
import os
import time
from urllib.parse import parse_qsl

from fastapi import HTTPException

# 🌟 ត្រូវកំណត់ជា environment variable ពេល deploy ជាក់ស្តែង, កុំ hardcode ក្នុងកូដ
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")

# 🌟 initData ចាស់ជាងនេះ (វិនាទី) នឹងត្រូវបដិសេធ ដើម្បីការពារ replay attack
INIT_DATA_MAX_AGE_SECONDS = 24 * 60 * 60  # 24 ម៉ោង

# 🌟 DEV BYPASS សម្រាប់ test នៅលើ Local (VS Code Live Server) ដោយមិនចាំបាច់បើកតាម Telegram ពិត។
# ត្រូវបើកដោយចេតនាតែប៉ុណ្ណោះ (env var), លំនាំដើមបិទជានិច្ច — ដូច្នេះមិនប៉ះពាល់សុវត្ថិភាព production ទេ។
# របៀបប្រើ (មុនចាប់ផ្ដើម server)៖
#   Windows (PowerShell):  $env:TELEGRAM_DEV_BYPASS="1"
#   Windows (cmd):         set TELEGRAM_DEV_BYPASS=1
# កុំដាក់ variable នេះនៅលើ server ជាក់ស្តែង (production) ជាដាច់ខាត។
DEV_BYPASS = os.environ.get("TELEGRAM_DEV_BYPASS", "") == "1"


def _compute_hash(data_check_string: str, bot_token: str) -> str:
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    return hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()


def validate_init_data(init_data: str) -> dict:
    """ផ្ទៀងផ្ទាត់ initData ដែលបញ្ជូនមកពី Telegram Web App ។
    ត្រឡប់ dict នៃ user object (id, first_name, ...) បើត្រឹមត្រូវ។
    បោះ HTTPException(401) បើ hash មិនត្រូវ, ខូច format, ឬផុតកំណត់ពេល។
    """
    if not TELEGRAM_BOT_TOKEN:
        # 🌟 គ្មាន Bot Token កំណត់ទេ (ឧ. dev/local environment) — មិនអាចផ្ទៀងផ្ទាត់បានទេ
        raise HTTPException(
            status_code=500,
            detail="TELEGRAM_BOT_TOKEN មិនត្រូវបានកំណត់នៅលើ server ទេ — មិនអាចផ្ទៀងផ្ទាត់ user បានទេ។",
        )

    if not init_data:
        raise HTTPException(status_code=401, detail="គ្មាន initData — សូមបើកកម្មវិធីនេះតាមរយៈ Telegram។")

    try:
        pairs = parse_qsl(init_data, strict_parsing=True)
    except ValueError:
        raise HTTPException(status_code=401, detail="initData មិនត្រឹមត្រូវ (format khusus)។")

    data = dict(pairs)
    received_hash = data.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=401, detail="initData គ្មាន hash — មិនអាចផ្ទៀងផ្ទាត់បានទេ។")

    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    expected_hash = _compute_hash(data_check_string, TELEGRAM_BOT_TOKEN)

    # 🌟 ប្រើ compare_digest ដើម្បីជៀសវាង timing attack
    if not hmac.compare_digest(received_hash, expected_hash):
        raise HTTPException(status_code=401, detail="initData hash មិនត្រូវគ្នា — សំណើនេះអាចត្រូវបានក្លែងបន្លំ។")

    auth_date = data.get("auth_date")
    if auth_date is not None:
        try:
            age = time.time() - int(auth_date)
        except ValueError:
            age = None
        if age is not None and age > INIT_DATA_MAX_AGE_SECONDS:
            raise HTTPException(status_code=401, detail="initData ផុតកំណត់ពេលហើយ — សូម reload កម្មវិធី។")

    user_json = data.get("user")
    if not user_json:
        raise HTTPException(status_code=401, detail="initData គ្មានទិន្នន័យ user។")

    try:
        user = json.loads(user_json)
    except json.JSONDecodeError:
        raise HTTPException(status_code=401, detail="initData.user មិនអាចអានបានទេ។")

    if "id" not in user:
        raise HTTPException(status_code=401, detail="initData.user គ្មាន id។")

    return user


def verify_user_id(init_data: str, claimed_user_id: int) -> None:
    """ផ្ទៀងផ្ទាត់ initData ហើយត្រូវប្រាកដថា user_id ដែល client អះអាង (claimed_user_id)
    ត្រូវគ្នាជាមួយ user_id ដែលបានចុះហត្ថលេខាដោយ Telegram ក្នុង initData ។
    ប្រើមុនធ្វើប្រតិបត្តិការណាមួយទាក់ទងនឹងលុយ (spin, wallet, pick-box, ...)។
    """
    if DEV_BYPASS:
        # 🌟 Local test mode — រំលងការផ្ទៀងផ្ទាត់ Telegram ទាំងស្រុង, ជឿលើ user_id ដែល client ផ្ញើមក
        return
    telegram_user = validate_init_data(init_data)
    if int(telegram_user["id"]) != int(claimed_user_id):
        raise HTTPException(
            status_code=403,
            detail="user_id មិនត្រូវគ្នាជាមួយ Telegram session បច្ចុប្បន្នទេ។",
        )