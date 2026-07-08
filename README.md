# Netanya Padel

אתר לרישום ותפעול טורנירי פאדל: הרשמת משתמשים, הרשמה לטורנירים כזוגות, הגרלת בתים אוטומטית, מעקב אחרי תוצאות ועלייה לשלב הנוקאאוט עד לכתרת זוג מנצח.

## פריסה חינמית (Supabase + Render)

### 1. Supabase (בסיס נתונים)
1. היכנס ל-https://supabase.com וצור פרויקט חדש (חינמי).
2. בתפריט **SQL Editor** הרץ את התוכן של `padel_setup.sql` שבתיקייה הזו — זה יוצר את כל הטבלאות.
3. בתפריט **Project Settings → API** העתק:
   - `Project URL` → זה יהיה `SUPABASE_URL`
   - `service_role` / `secret` key (בסודי, שרת בלבד!) → זה יהיה `SUPABASE_SERVICE_KEY`
   - `anon` / `publishable` key (בטוח לחשיפה) → זה יהיה `SUPABASE_ANON_KEY`

### 1א. אימות טלפון ב-SMS (חובה כדי שהרשמה תעבוד!)
ההרשמה לאתר שולחת קוד אימות ב-SMS דרך המנגנון המובנה של Supabase Auth. **בלי הגדרה הזו, שום משתמש חדש לא יוכל להירשם.**
1. ב-Supabase: **Authentication → Sign In / Providers → Phone**, הפעל אותו.
2. בחר ספק SMS (למשל Twilio) והזן את הפרטים/מפתחות שלו. זה כרוך בתשלום קטן לפי הודעה אצל הספק (Supabase עצמו לא גובה על זה, אבל אין ספק SMS אמיתי שהוא חינמי לחלוטין).
3. אם כבר יש לך ספק SMS מוגדר בפרויקט Supabase אחר (למשל goplayorder), אפשר להשתמש באותם פרטי חשבון כאן.

### 2. GitHub
1. צור ריפו חדש (למשל `netanya-padel`) והעלה אליו את כל התיקייה הזו.

### 3. Render (שרת)
1. היכנס ל-https://render.com, **New → Web Service**, חבר את הריפו מ-GitHub.
2. Build command: (ריק, לא נדרש) · Start command: נלקח אוטומטית מה-`Procfile`.
3. הגדר את משתני הסביבה הבאים ב-**Environment**:
   - `SUPABASE_URL` — מ-Supabase שלב 1
   - `SUPABASE_SERVICE_KEY` — מ-Supabase שלב 1 (ה-service_role/secret, לא ה-anon key)
   - `SUPABASE_ANON_KEY` — מ-Supabase שלב 1 (ה-anon/publishable key)
   - `SECRET_KEY` — כל מחרוזת אקראית ארוכה (למשל: `openssl rand -hex 32`)
   - `ADMIN_USERNAME` — שם המשתמש שתירשם איתו, יקבל אוטומטית הרשאות ניהול
4. פרסם. השירות החינמי של Render "נרדם" אחרי חוסר פעילות ומתעורר תוך כמה שניות בבקשה הבאה — תקין ל-MVP.

### 4. שימוש ראשוני
1. היכנס לאתר, לחץ "הרשמה" והירשם עם שם המשתמש שהגדרת ב-`ADMIN_USERNAME` — תקבל אוטומטית הרשאות אדמין.
2. כאדמין תוכל ליצור טורניר חדש, להוסיף זוגות ישירות, ולנהל את הטורניר עד הסוף.

## הרצה מקומית

```bash
pip install -r requirements.txt
export SUPABASE_URL=...
export SUPABASE_SERVICE_KEY=...
export SUPABASE_ANON_KEY=...
export SECRET_KEY=dev-secret
export ADMIN_USERNAME=admin
python app.py
```

השרת יעלה בכתובת http://localhost:5000
