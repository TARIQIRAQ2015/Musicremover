import json
import logging
import os
import re
import subprocess
from urllib.parse import urlparse

import yt_dlp
import streamlit as st

"""
هذا هو تطبيق Fast Music Remover المبني على Streamlit.

سير العمل:
1) قبول رابط فيديو أو ملف فيديو مرفوع من المستخدم.
   - إذا تم توفير رابط، يتم تنزيل الفيديو عبر `yt-dlp` وتنظيف اسم الملف.
   - إذا تم رفع ملف، يتم حفظه مباشرة في مجلد التحميلات بعد تنظيف اسم الملف.

2) إرسال طلب المعالجة إلى برنامج `MediaProcessor` المكتوب بلغة ++C.
   - يقوم `MediaProcessor` بتصفية الملف المدخل وحفظه في نفس المجلد باسم فريد.

3) عرض الفيديو المعالج في الواجهة الأمامية.
   - يتم عرض الفيديو النهائي للمستخدم مع إمكانية تحميله.
"""

# تحميل الإعدادات وتعيين المسارات
with open("config.json") as config_file:
    config = json.load(config_file)

# تعريف المسارات الأساسية باستخدام مراجع مطلقة
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DOWNLOADS_PATH = os.path.abspath(config["downloads_path"])
UPLOADS_PATH = os.path.abspath(config.get("uploads_path", os.path.join(BASE_DIR, "uploads")))

DEEPFILTERNET_PATH = os.path.abspath(config["deep_filter_path"])
FFMPEG_PATH = os.path.abspath(config["ffmpeg_path"])

os.environ["DEEPFILTERNET_PATH"] = DEEPFILTERNET_PATH

class Utils:
    """فئة المساعدة للعمليات الشائعة مثل تنظيف الملفات وتنظيمها."""

    @staticmethod
    def ensure_dir_exists(directory):
        if not os.path.exists(directory):
            os.makedirs(directory)

    @staticmethod
    def remove_files_by_base(base_filename):
        """إزالة أي ملفات موجودة لها نفس الاسم الأساسي."""
        base_path = os.path.join(UPLOADS_PATH, base_filename)
        file_paths = [base_path + ".webm", base_path + "_isolated_audio.wav", base_path + "_processed_video.mp4"]
        for path in file_paths:
            if os.path.exists(path):
                logging.info(f"إزالة الملف القديم: {path}")
                os.remove(path)

    @staticmethod
    def sanitize_filename(filename):
        """استبدال الأحرف غير الأبجدية الرقمية (باستثناء النقاط والشرطات السفلية) بشرطات سفلية."""
        return re.sub(r"[^a-zA-Z0-9._-]", "_", filename)

    @staticmethod
    def validate_url(url):
        """التحقق الأساسي من صحة الرابط."""
        parsed_url = urlparse(url)
        return all([parsed_url.scheme, parsed_url.netloc])

# التأكد من وجود مجلد التحميلات
Utils.ensure_dir_exists(UPLOADS_PATH)

class MediaHandler:
    """فئة للتعامل مع تحميل ومعالجة الفيديو."""

    @staticmethod
    def download_media(url):
        try:
            # استخراج معلومات الوسائط أولاً لتنظيف العنوان
            with yt_dlp.YoutubeDL() as ydl:
                info_dict = ydl.extract_info(url, download=False)
                base_title = info_dict["title"]
                sanitized_title = Utils.sanitize_filename(base_title)

            ydl_opts = {
                "format": "bestvideo+bestaudio/best",
                "outtmpl": os.path.join(UPLOADS_PATH, sanitized_title + ".%(ext)s"),
                "noplaylist": True,
                "keepvideo": True,
                "n_threads": 6,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result = ydl.extract_info(url, download=True)

                if "requested_formats" in result:
                    merged_ext = result["ext"]
                else:
                    merged_ext = result.get("ext", "mp4")

            video_file = os.path.join(UPLOADS_PATH, sanitized_title + "." + merged_ext)
            return os.path.abspath(video_file)

        except Exception as e:
            st.error(f"خطأ في تحميل الفيديو: {e}")
            return None

    @staticmethod
    def detect_media_type(file_path):
        """استخدام ffprobe للكشف عما إذا كانت الوسائط صوتية أو مرئية."""
        try:
            command = [
                "ffprobe",
                "-loglevel",
                "error",
                "-show_entries",
                "stream=codec_type",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                file_path,
            ]
            result = subprocess.run(command, capture_output=True, text=True, check=True)
            output = result.stdout.strip()

            if "video" in output:
                return "video"
            elif "audio" in output:
                return "audio"
            else:
                return None
        except subprocess.CalledProcessError as e:
            st.error(f"خطأ في الكشف عن نوع الوسائط: {e.stderr}")
            return None

    @staticmethod
    def process_with_media_processor(media_path):
        """معالجة الملف المعطى باستخدام MediaProcessor."""
        try:
            with st.spinner('جاري معالجة الملف...'):
                result = subprocess.run(
                    ["./MediaProcessor/build/MediaProcessor", str(media_path)], 
                    capture_output=True, 
                    text=True
                )

                if result.returncode != 0:
                    st.error("فشلت عملية المعالجة.")
                    return None

                for line in result.stdout.splitlines():
                    if "Video processed successfully" in line or "Audio processed successfully" in line:
                        processed_media_path = line.split(": ", 1)[1].strip()
                        if processed_media_path.startswith('"') and processed_media_path.endswith('"'):
                            processed_media_path = processed_media_path[1:-1]
                        return os.path.abspath(processed_media_path)

                st.error("لم يتم العثور على مسار الملف المعالج.")
                return None

        except Exception as e:
            st.error(f"خطأ في تشغيل MediaProcessor: {e}")
            return None

def main():
    # تعيين نمط الصفحة
    st.set_page_config(
        page_title="Fast Music Remover",
        page_icon="🎵",
        layout="wide",
    )

    # إضافة CSS مخصص
    st.markdown("""
        <style>
        .main {
            background-color: #f5f5f5;
        }
        .stButton>button {
            width: 100%;
            border-radius: 10px;
            height: 3em;
            background-color: #FF4B4B;
            color: white;
            border: none;
            margin-top: 20px;
        }
        .stButton>button:hover {
            background-color: #FF2E2E;
            border: none;
        }
        .upload-header {
            text-align: center;
            padding: 20px;
            border-radius: 10px;
            background-color: #ffffff;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }
        </style>
    """, unsafe_allow_html=True)

    # تصميم الهيدر
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.markdown("""
            <div class="upload-header">
                <h1 style='text-align: center; color: #FF4B4B;'>🎵 Fast Music Remover</h1>
                <p style='text-align: center; color: #666666;'>قم بإزالة الموسيقى من مقاطع الفيديو بسهولة</p>
            </div>
        """, unsafe_allow_html=True)

    # إنشاء التصميم الرئيسي
    left_col, right_col = st.columns([2,1])

    with left_col:
        # إنشاء علامتي تبويب بتصميم جديد
        tabs = st.tabs(["📤 رفع ملف", "🔗 رابط يوتيوب"])
        
        with tabs[0]:
            st.markdown("### قم برفع ملف فيديو")
            st.markdown("##### الصيغ المدعومة: MP4, WEBM, AVI")
            uploaded_file = st.file_uploader("", type=['mp4', 'webm', 'avi'])
            
            if uploaded_file:
                with st.spinner('⏳ جاري رفع الملف...'):
                    sanitized_filename = Utils.sanitize_filename(uploaded_file.name)
                    video_path = os.path.join(UPLOADS_PATH, sanitized_filename)
                    with open(video_path, "wb") as f:
                        f.write(uploaded_file.getbuffer())
                    
                    # إضافة شريط تقدم
                    progress_bar = st.progress(0)
                    for i in range(100):
                        progress_bar.progress(i + 1)
                    
                    processed_video_path = MediaHandler.process_with_media_processor(video_path)
                    if processed_video_path:
                        st.success("✅ تمت معالجة الفيديو بنجاح!")
                        
                        # إضافة زر للتحميل بتصميم جديد
                        with open(processed_video_path, "rb") as file:
                            st.download_button(
                                label="⬇️ تحميل الفيديو المعالج",
                                data=file,
                                file_name=os.path.basename(processed_video_path),
                                mime="video/mp4"
                            )
        
        with tabs[1]:
            st.markdown("### أدخل رابط فيديو يوتيوب")
            url = st.text_input("", placeholder="https://www.youtube.com/watch?v=...")
            
            if url:
                if Utils.validate_url(url):
                    with st.spinner('⏳ جاري تحميل الفيديو...'):
                        # إضافة شريط تقدم
                        progress_bar = st.progress(0)
                        video_path = MediaHandler.download_media(url)
                        
                        if video_path:
                            for i in range(100):
                                progress_bar.progress(i + 1)
                            
                            processed_video_path = MediaHandler.process_with_media_processor(video_path)
                            if processed_video_path:
                                st.success("✅ تمت معالجة الفيديو بنجاح!")
                                
                                # إضافة زر للتحميل
                                with open(processed_video_path, "rb") as file:
                                    st.download_button(
                                        label="⬇️ تحميل الفيديو المعالج",
                                        data=file,
                                        file_name=os.path.basename(processed_video_path),
                                        mime="video/mp4"
                                    )
                else:
                    st.error("❌ الرابط غير صالح")

    with right_col:
        # عرض الفيديو المعالج
        if 'processed_video_path' in locals():
            st.markdown("### معاينة الفيديو")
            st.video(processed_video_path)
            
            # إضافة معلومات إضافية
            st.markdown("### تفاصيل المعالجة")
            with st.expander("إحصائيات الملف"):
                file_size = os.path.getsize(processed_video_path) / (1024 * 1024)  # تحويل إلى ميجابايت
                st.write(f"📁 حجم الملف: {file_size:.2f} MB")
                st.write(f"📝 اسم الملف: {os.path.basename(processed_video_path)}")
                media_type = MediaHandler.detect_media_type(processed_video_path)
                st.write(f"📺 نوع الملف: {media_type}")

    # إضافة فوتر
    st.markdown("""
        <div style='text-align: center; color: #666666; padding: 20px;'>
            <p>تم التطوير بواسطة Fast Music Remover Team</p>
        </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__":
    main()
