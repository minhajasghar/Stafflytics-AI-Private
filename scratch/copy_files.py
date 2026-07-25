import shutil
import os

src_base = r"c:\Users\Sultan Mahmood\Desktop\Test\stafflytics-ai"
dst_base = r"c:\Users\Sultan Mahmood\Desktop\stafflytics\stafflytics-ai"

files = [
    "app.py",
    "database.py",
    "stream_manager.py",
    "vision_engine.py",
    "templates/index.html",
    "static/js/main.js"
]

print("Copying implemented project files to the active workspace...")
for f in files:
    src_path = os.path.join(src_base, f)
    dst_path = os.path.join(dst_base, f)
    dst_dir = os.path.dirname(dst_path)
    
    if not os.path.exists(dst_dir):
        os.makedirs(dst_dir)
        
    try:
        shutil.copy2(src_path, dst_path)
        print(f"Copied: {f}")
    except Exception as e:
        print(f"Error copying {f}: {e}")

# Apply User's environment options edit to the copied app.py
app_path = os.path.join(dst_base, "app.py")
try:
    with open(app_path, "r", encoding="utf-8") as file:
        content = file.read()
        
    old_line = 'os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp|max_delay;2000000|fflags;+genpts+igndts"'
    new_line = 'os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport=tcp|max_delay=2000000|loglevel=fatal"'
    
    if old_line in content:
        content = content.replace(old_line, new_line)
        with open(app_path, "w", encoding="utf-8") as file:
            file.write(content)
        print("Successfully merged user's custom OpenCV environment flags into app.py.")
    else:
        print("Note: Custom OpenCV environment flags already merged or line not found.")
except Exception as e:
    print(f"Error merging user edit: {e}")
