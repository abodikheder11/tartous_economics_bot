# Telegram bot starter for اقتصاد طرطوس

هذا مشروع أولي لبوت تيليجرام خاص بطلاب كلية الاقتصاد في طرطوس.

## الملفات

- `bot.py` : الكود الرئيسي
- `content_catalog.json` : الفهرس الذي تعدّل فيه أسماء المواد والملفات
- `content/` : ضع فيه ملفات الـ PDF

## التشغيل

1. أنشئ bot من BotFather وخذ التوكن.
2. ثبّت المتطلبات:
   `pip install -r requirements.txt`
3. في لينكس/ماك:
   `export BOT_TOKEN="ضع_التوكن_هنا"`
4. في ويندوز PowerShell:
   `$env:BOT_TOKEN="XXXXXXX"`
5. شغّل:
   `python3 bot.py`
