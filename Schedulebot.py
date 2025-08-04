# Schedulebot.py
import os
import logging
from datetime import datetime, date, time, timedelta
import pytz
import requests
from dateutil import parser
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes
)
import db  # db.py must implement get_notice_flag, set_notice_flag

# 日誌設定
logging.basicConfig(level=logging.INFO)

# 時區
TZ = pytz.timezone("Asia/Taipei")

origin = "下列為機器人的主要功能 ! 請選擇： \n📅 Today : 顯示今日課程資訊 \n🔎 Find : 輸入 mm-dd 即可獲得當日課程資訊\n🔔 Notice : 顯示目前是否通知的狀態"

# 讀取 env
load_dotenv()
API_BASE = os.getenv("API_BASE")
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN")
if not API_BASE or not TG_BOT_TOKEN:
    logging.error("請在 .env 中設置 API_BASE 和 TG_BOT_TOKEN")
    exit(1)


# 建立按鈕選單
def get_keyboard(chat_id=None):
    on15 = db.get_notice_flag(chat_id, 15)
    on30 = db.get_notice_flag(chat_id, 30)
    return InlineKeyboardMarkup([
        [ InlineKeyboardButton("Today", callback_data="today"),InlineKeyboardButton("Find mm-dd", callback_data="find")],
        [InlineKeyboardButton(f"15min Notice: {'On' if on15 else 'Off'}", callback_data="toggle15"),InlineKeyboardButton(f"30min Notice: {'On' if on30 else 'Off'}", callback_data="toggle30")]
    ])

# 啟動指令
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    db.add_user(cid)
    token = db.get_user_token(cid)
    if not token:
        await update.message.reply_text("👋 歡迎！請使用 /settoken <API_TOKEN> 進行綁定。")
    else:
        await update.message.reply_text(origin, reply_markup=get_keyboard(cid))

# 綁定 token
async def settoken(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    args = context.args
    if not args:
        return await update.message.reply_text("請提供 API_TOKEN，例如 /settoken abc123")
    db.set_user_token(cid, args[0])
    await update.message.reply_text("✅ Token 已綁定！", reply_markup=get_keyboard(cid))

# 重設 token
async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("請輸入新的 API_TOKEN：")
    context.user_data['awaiting_reset'] = True

# 排程提醒
async def daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    # 每日早上8點提醒今日課程
    for user in db.get_all_users():
        cid = user['chatid']
        try:
            text = await fetch_and_format(cid, datetime.now(TZ).date())
            await context.bot.send_message(chat_id=cid, text=text)
            await context.bot.send_message(chat_id=cid, text=origin, reply_markup=get_keyboard(cid))

            lessons = await fetch_and_format(cid,  datetime.now(TZ).date())
            for s, e, name in lessons:
                for minutes in (15, 30):
                    if db.get_notice_flag(cid, minutes):
                        logging.info("排程提醒前：User %s, 15min=%s, 30min=%s", cid, db.get_notice_flag(cid,15), db.get_notice_flag(cid,30))
                        remind_time = s - timedelta(minutes=minutes)
                        if remind_time > now:
                            context.job_queue.run_once(
                                callback=course_reminder,
                                when=remind_time,
                                chat_id=cid,
                                name=f"notice_{cid}_{int(s.timestamp())}_{minutes}",
                                data={"name": name, "minutes": minutes}
                        )

        except Exception as e:
            logging.error(f"daily_reminder error for {cid}: {e}")


async def night_reminder(context: ContextTypes.DEFAULT_TYPE):
    # 前一日晚上9點提醒明日課程
    tgt = datetime.now(TZ).date() + timedelta(days=1)
    for user in db.get_all_users():
        cid = user['chatid']
        try:
            text = await fetch_and_format(cid, tgt)
            await context.bot.send_message(chat_id=cid, text=text)
            await context.bot.send_message(chat_id=cid, text=origin, reply_markup=get_keyboard(cid))
        except Exception as e:
            logging.error(f"night_reminder error for {cid}: {e}")

# 切換通知設定
async def toggle_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid = update.effective_chat.id
    q = update.callback_query
    await q.answer()
    key = q.data
    if key == 'toggle15':
        cur = db.get_notice_flag(cid, 15)
        db.set_notice_flag(cid, 15, not cur)
        await q.edit_message_text(f"15分鐘提醒已{'開啟' if not cur else '關閉'}。", reply_markup=get_keyboard(cid))
    elif key == 'toggle30':
        cur = db.get_notice_flag(cid, 30)
        db.set_notice_flag(cid, 30, not cur)
        await q.edit_message_text(f"30分鐘提醒已{'開啟' if not cur else '關閉'}。", reply_markup=get_keyboard(cid))

# 構建 URL
async def build_api_url(cid: int, tgt: date) -> str:
    token = db.get_user_token(cid)
    base = API_BASE.rstrip('/')
    start = tgt.isoformat() + 'T00:00:00%2B08:00'
    end = (tgt + timedelta(days=1)).isoformat() + 'T00:00:00%2B08:00'
    return f"{base}/{token}/list?startAt={start}&endAt={end}&isNotReject=true"

# 抓取並格式化
async def fetch_and_format(cid: int, tgt: date) -> str:
    url = await build_api_url(cid, tgt)
    data = requests.get(url).json()
    courses = data.get('data',{}).get('courses',[])
    lessons=[]
    for c in courses:
        if c.get('intervalStatus')=='cancel': continue
        s=parser.parse(c['startAt'].split(' (',1)[0]).astimezone(TZ)
        e=parser.parse(c['endAt'].split(' (',1)[0]).astimezone(TZ)
        if s.date()==tgt:
            lessons.append((s,e,c['name'],c['intervalStatus'],c.get('students',[])))
    lessons.sort(key=lambda x:x[0])
    if not lessons: return f"{tgt} \n🍻 今天沒有課程喔~ 又是難得的休假日 🍻 "
    out=[f"{tgt} 課程列表："]
    for s,e,name,st,stu in lessons:
        if st=='over' or st=='finish': 
            name=f"[✅] {name} "
        names='、'.join([x.get('name','') for x in stu]) or '(無學生)'
        out += [f"🔹 {name}", f"  • 日期:{s.strftime('%Y-%m-%d')}", f"  • 時間：{s.strftime('%H:%M')}–{e.strftime('%H:%M')}", f"  • 學生：{names}\n"]
    return '\n'.join(out)

# 處按鈕
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid=update.effective_chat.id; q=update.callback_query; await q.answer()
    if q.data in('toggle15','toggle30'):
        return await toggle_handler(update,context)
    if q.data=='today':
        text=await fetch_and_format(cid,datetime.now(TZ).date())
    else:
        await q.edit_message_text("請輸入日期 mm-dd，例如 08-05：")
        context.user_data['awaiting_find']=True; return
    await q.edit_message_text(text)
    await q.message.reply_text(origin,reply_markup=get_keyboard(cid))

# 處理文字
async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cid=update.effective_chat.id
    if context.user_data.pop('awaiting_reset',False):
        db.set_user_token(cid,update.message.text.strip())
        return await update.message.reply_text("✅ Token 更新！",reply_markup=get_keyboard(cid))
    if context.user_data.pop('awaiting_find',False):
        try:
            m,d=map(int,update.message.text.split('-',1)); tgt=date(datetime.now(TZ).year,m,d)
            res=await fetch_and_format(cid,tgt)
        except:
            res="格式錯誤，請用 mm-dd。"
        await update.message.reply_text(res)
        return await update.message.reply_text(origin,reply_markup=get_keyboard(cid))

# --- 課程前提醒 callback ---
async def course_reminder(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    cid = job.chat_id
    name = job.data.get('name')
    minutes = job.data.get('minutes')
    await context.bot.send_message(
        chat_id=cid,
        text=f"⏰ 「{name}」將於 {minutes} 分鐘後開始，請準備！"
    )


if __name__=='__main__':
    app=ApplicationBuilder().token(TG_BOT_TOKEN).build()
    
    now = datetime.now(TZ) 

    print(f"Current time: {now.time()}")


    # 基本指令
    app.add_handler(CommandHandler('start',start))
    app.add_handler(CommandHandler('settoken',settoken))
    app.add_handler(CommandHandler('reset',reset))
    # 按鈕
    app.add_handler(CallbackQueryHandler(button_handler))
    # 文字
    app.add_handler(MessageHandler(filters.TEXT&~filters.COMMAND,text_handler))
    
    # 排程
    job_q = app.job_queue
    job_q.run_daily(daily_reminder, time=time(hour=8, minute=0, second=0,tzinfo=TZ))
    job_q.run_daily(night_reminder, time=time(hour=21, minute=0,second=0, tzinfo=TZ)) 

    # 測資們 
    # job_q.run_repeating(daily_reminder, interval=10, first=5)
    # logging.info("Scheduled daily_reminder every 10 seconds starting in 5 seconds")
    # job_q.run_repeating(night_reminder, interval=10, first=5) 
    # job_q.run_daily(daily_reminder,time=time(hour=4,minute=42,second=0,tzinfo=TZ))  # 每日早上4:36提醒今日課程 
    # job_q.run_daily(night_reminder,time=time(hour=4,minute=43,second=0,tzinfo=TZ))  # 每日早上4:36提醒今日課程 


    app.run_polling()

