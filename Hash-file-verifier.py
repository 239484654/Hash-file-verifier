import os
import hashlib
import zlib
import sqlite3
import wx
import datetime
import psutil
import threading
import ctypes
import sys

# 创建一个锁对象
db_lock = threading.Lock()

def is_file_locked(file_path):
    """
    检查文件是否被锁定（正在被写入或更改）
    """
    try:
        with open(file_path, 'a'):
            pass
        return False
    except PermissionError:
        return True


def calculate_hash(file_path, algorithm):
    if algorithm == 'MD5':
        hash_obj = hashlib.md5()
        with open(file_path, 'rb') as file:
            for chunk in iter(lambda: file.read(4096), b""):
                hash_obj.update(chunk)
        return hash_obj.hexdigest()
    elif algorithm == 'CRC32':
        hash_obj = 0
        with open(file_path, 'rb') as file:
            for chunk in iter(lambda: file.read(4096), b""):
                hash_obj = zlib.crc32(chunk, hash_obj)
        return hex(hash_obj & 0xFFFFFFFF)[2:]
    elif algorithm == 'SHA-256':
        hash_obj = hashlib.sha256()
        with open(file_path, 'rb') as file:
            for chunk in iter(lambda: file.read(4096), b""):
                hash_obj.update(chunk)
        return hash_obj.hexdigest()
    elif algorithm == 'SHA-512':
        hash_obj = hashlib.sha512()
        with open(file_path, 'rb') as file:
            for chunk in iter(lambda: file.read(4096), b""):
                hash_obj.update(chunk)
        return hash_obj.hexdigest()
    else:
        raise ValueError("不支持的哈希算法")


def process_files(file_or_dir, algorithms, db_path, progress_bar):
    try:
        file_or_dir = os.path.expandvars(file_or_dir)
    except Exception:
        pass
    try:
        if not os.path.exists(file_or_dir):
            return 0, 0, f"输入的文件或文件夹路径 {file_or_dir} 不存在。"
    except PermissionError:
        return 0, 0, f"没有足够的权限访问路径 {file_or_dir}。"

    try:
        db_path = os.path.expandvars(db_path)
    except Exception:
        pass
    try:
        if not os.path.exists(os.path.dirname(db_path)):
            return 0, 0, f"数据库保存路径 {os.path.dirname(db_path)} 不存在。"
    except PermissionError:
        return 0, 0, f"没有足够的权限访问数据库保存路径 {os.path.dirname(db_path)}。"

    # 获取锁
    with db_lock:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        # 创建新的数据库表结构
        cursor.execute('''CREATE TABLE IF NOT EXISTS hashes
                          (file_path TEXT, write_time TEXT, MD5 TEXT, CRC32 TEXT, SHA_256 TEXT, SHA_512 TEXT)''')

        if file_or_dir is None:
            return 0, 0, ""

        success_count = 0
        fail_count = 0
        error_message = ""

        if os.path.isfile(file_or_dir):
            md5 = ""
            crc32 = ""
            sha256 = ""
            sha512 = ""
            if file_or_dir == db_path:
                fail_count += 1
                error_message = f"跳过数据库文件 {db_path} 的哈希计算。"
            elif is_file_locked(file_or_dir):
                fail_count += 1
                error_message = f"文件 {file_or_dir} 正在被写入或更改，跳过计算。"
            else:
                try:
                    if 'MD5' in algorithms:
                        md5 = calculate_hash(file_or_dir, 'MD5')
                    if 'CRC32' in algorithms:
                        crc32 = calculate_hash(file_or_dir, 'CRC32')
                    if 'SHA-256' in algorithms:
                        sha256 = calculate_hash(file_or_dir, 'SHA-256')
                    if 'SHA-512' in algorithms:
                        sha512 = calculate_hash(file_or_dir, 'SHA-512')
                    success_count += 1
                except Exception as e:
                    print(f"处理文件 {file_or_dir} 时出错: {e}")
                    fail_count += 1
            write_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("INSERT INTO hashes VALUES (?,?,?,?,?,?)", (file_or_dir, write_time, md5, crc32, sha256, sha512))
        elif os.path.isdir(file_or_dir):
            all_files = []
            try:
                for root, dirs, files in os.walk(file_or_dir):
                    for file in files:
                        file_path = os.path.join(root, file)
                        if file_path != db_path:
                            all_files.append(file_path)
            except PermissionError:
                return 0, 0, f"没有足够的权限访问目录 {file_or_dir}。"
            total_files = len(all_files)
            for index, file_path in enumerate(all_files):
                md5 = ""
                crc32 = ""
                sha256 = ""
                sha512 = ""
                if is_file_locked(file_path):
                    print(f"文件 {file_path} 正在被写入或更改，跳过计算。")
                    fail_count += 1
                else:
                    try:
                        if 'MD5' in algorithms:
                            md5 = calculate_hash(file_path, 'MD5')
                        if 'CRC32' in algorithms:
                            crc32 = calculate_hash(file_path, 'CRC32')
                        if 'SHA-256' in algorithms:
                            sha256 = calculate_hash(file_path, 'SHA-256')
                        if 'SHA-512' in algorithms:
                            sha512 = calculate_hash(file_path, 'SHA-512')
                        success_count += 1
                    except Exception as e:
                        print(f"处理文件 {file_path} 时出错: {e}")
                        fail_count += 1
                write_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                cursor.execute("INSERT INTO hashes VALUES (?,?,?,?,?,?)", (file_path, write_time, md5, crc32, sha256, sha512))
                def update_progress():
                    progress = (index + 1) / total_files * 100
                    progress_bar.SetValue(int(progress))
                    wx.Yield()
                wx.CallAfter(update_progress)

        conn.commit()
        conn.close()
    return success_count, fail_count, error_message


class HashCalculatorGUI(wx.Frame):
    def __init__(self, parent, title):
        super(HashCalculatorGUI, self).__init__(parent, title=title, size=(600, 400))

        panel = wx.Panel(self)

        # 多选框
        self.md5_checkbox = wx.CheckBox(panel, label="MD5", pos=(20, 20))
        self.crc32_checkbox = wx.CheckBox(panel, label="CRC32", pos=(120, 20))
        self.sha256_checkbox = wx.CheckBox(panel, label="SHA-256", pos=(220, 20))
        self.sha512_checkbox = wx.CheckBox(panel, label="SHA-512", pos=(320, 20))

        # 绑定多选框的事件
        self.md5_checkbox.Bind(wx.EVT_CHECKBOX, self.on_checkbox_change)
        self.crc32_checkbox.Bind(wx.EVT_CHECKBOX, self.on_checkbox_change)
        self.sha256_checkbox.Bind(wx.EVT_CHECKBOX, self.on_checkbox_change)
        self.sha512_checkbox.Bind(wx.EVT_CHECKBOX, self.on_checkbox_change)

        # 选择路径按钮
        self.select_path_button = wx.Button(panel, label="浏览", pos=(20, 60))
        self.select_path_button.Bind(wx.EVT_BUTTON, self.on_select_path)
        self.path_text = wx.TextCtrl(panel, pos=(120, 60), size=(300, -1))
        self.path_text.SetHint("请在此输入文件夹路径")

        # 选择保存路径按钮
        self.select_save_path_button = wx.Button(panel, label="浏览", pos=(20, 100))
        self.select_save_path_button.Bind(wx.EVT_BUTTON, self.on_select_save_path)
        self.save_path_text = wx.TextCtrl(panel, pos=(120, 100), size=(300, -1))
        self.save_path_text.SetHint("请在此输入数据库生成路径")

        # 完成按钮
        self.finish_button = wx.Button(panel, label="完成", pos=(20, 140))
        self.finish_button.Bind(wx.EVT_BUTTON, self.on_finish)

        # 进度条
        self.progress_bar = wx.Gauge(panel, pos=(20, 180), size=(500, 25))

        # 初始化完成按钮状态
        self.update_finish_button_state()

        self.Centre()
        self.Show()

    def on_checkbox_change(self, event):
        # 多选框状态改变时更新完成按钮状态
        self.update_finish_button_state()

    def update_finish_button_state(self):
        # 检查是否有复选框被选中且选择了路径
        any_checked = (self.md5_checkbox.IsChecked() or
                       self.crc32_checkbox.IsChecked() or
                       self.sha256_checkbox.IsChecked() or
                       self.sha512_checkbox.IsChecked())
        path_selected = bool(self.path_text.GetValue()) and bool(self.save_path_text.GetValue())
        # 根据状态启用或禁用完成按钮
        self.finish_button.Enable(any_checked and path_selected)

    def on_select_path(self, event):
        path = self.path_text.GetValue()
        default_path = ""
        try:
            if path:
                expanded_path = os.path.expandvars(path)
                if os.path.exists(expanded_path):
                    default_path = expanded_path
                else:
                    self.path_text.SetValue("")
        except Exception:
            self.path_text.SetValue("")

        dlg = wx.DirDialog(self, "选择文件夹", defaultPath=default_path)
        if dlg.ShowModal() == wx.ID_OK:
            path = dlg.GetPath()
            self.path_text.SetValue(path)
        dlg.Destroy()
        self.update_finish_button_state()

    def on_select_save_path(self, event):
        path = self.save_path_text.GetValue()
        default_dir = ""
        try:
            if path:
                expanded_path = os.path.expandvars(path)
                parent_dir = os.path.dirname(expanded_path)
                if os.path.exists(parent_dir):
                    default_dir = parent_dir
                else:
                    self.save_path_text.SetValue("")
        except Exception:
            self.save_path_text.SetValue("")

        dlg = wx.FileDialog(self, "另存为", defaultDir=default_dir, wildcard="数据库文件 (*.db)|*.db", style=wx.FD_SAVE)
        if dlg.ShowModal() == wx.ID_OK:
            save_path = dlg.GetPath()
            self.save_path_text.SetValue(save_path)
        dlg.Destroy()
        self.update_finish_button_state()

    def on_finish(self, event):
        file_or_dir = self.path_text.GetValue()
        db_path = self.save_path_text.GetValue()
        algorithms = []
        if self.md5_checkbox.IsChecked():
            algorithms.append('MD5')
        if self.crc32_checkbox.IsChecked():
            algorithms.append('CRC32')
        if self.sha256_checkbox.IsChecked():
            algorithms.append('SHA-256')
        if self.sha512_checkbox.IsChecked():
            algorithms.append('SHA-512')

        def run_process():
            total_success, total_fail, error_message = process_files(file_or_dir, algorithms, db_path, self.progress_bar)

            total_count = total_success + total_fail
            if total_count == 0:
                if error_message:
                    message = error_message
                    icon = wx.ICON_ERROR
                else:
                    message = "未选择有效的文件或文件夹。"
                    icon = wx.ICON_ERROR
            elif total_fail == 0:
                message = f"哈希计算完成，所有 {total_success} 个文件的结果已成功保存到 {db_path}。"
                icon = wx.ICON_INFORMATION
            elif total_success == 0:
                message = f"所有 {total_fail} 个文件在哈希计算和保存过程中均失败。"
                icon = wx.ICON_ERROR
            else:
                message = f"哈希计算完成，{total_success} 个文件成功保存到 {db_path}，{total_fail} 个文件处理失败。"
                icon = wx.ICON_WARNING

            def show_message():
                wx.MessageBox(message, "操作结果", wx.OK | icon)
            wx.CallAfter(show_message)

        thread = threading.Thread(target=run_process)
        thread.start()


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False


if __name__ == "__main__":
    if is_admin():
        app = wx.App()
        HashCalculatorGUI(None, "哈希计算工具")
        app.MainLoop()
    else:
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, " ".join(sys.argv), None, 1)
