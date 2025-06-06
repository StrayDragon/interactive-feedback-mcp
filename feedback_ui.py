import os
import sys
import json
import psutil
import threading
# import argparse # No longer needed
import subprocess
# import threading # No longer using Python threads for GUI directly from FastAPI endpoint
import hashlib
# import queue # For thread-safe communication, will use multiprocessing.Queue
from typing import Optional, TypedDict, List

from multiprocessing import Process, Queue as MPQueue # For inter-process communication
import queue # Standard queue module for MPQueue.get() timeout exception

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QTextEdit, QGroupBox
)
from PySide6.QtCore import Qt, Signal, QObject, QTimer, QSettings, QThread
from PySide6.QtGui import QTextCursor, QIcon, QKeyEvent, QFont, QFontDatabase, QPalette, QColor

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn

# --- TypedDicts (can also be Pydantic models for FastAPI response) ---
class FeedbackResult(TypedDict):
    logs: str 
    interactive_feedback: str

class FeedbackConfig(TypedDict):
    run_command: str
    execute_automatically: bool

# --- Helper Functions (from original script) ---
def set_dark_title_bar(widget: QWidget, dark_title_bar: bool) -> None:
    if sys.platform != "win32":
        return
    from ctypes import windll, c_uint32, byref
    build_number = sys.getwindowsversion().build
    if build_number < 17763:
        return
    dark_prop = widget.property("DarkTitleBar")
    if dark_prop is not None and dark_prop == dark_title_bar:
        return
    widget.setProperty("DarkTitleBar", dark_title_bar)
    dwmapi = windll.dwmapi
    hwnd = widget.winId()
    attribute = 20 if build_number >= 18985 else 19
    c_dark_title_bar = c_uint32(dark_title_bar)
    dwmapi.DwmSetWindowAttribute(hwnd, attribute, byref(c_dark_title_bar), 4)
    try:
        temp_widget = QWidget(None, Qt.FramelessWindowHint | Qt.Tool)
        temp_widget.resize(1, 1)
        temp_widget.move(widget.pos().x() - 10000, widget.pos().y() - 10000)
        temp_widget.show()
        QTimer.singleShot(50, temp_widget.deleteLater)
    except Exception as e:
        print(f"Note: Dark title bar redraw hack minor issue: {e}")
        pass


def get_dark_mode_palette(app: QApplication):
    darkPalette = app.palette()
    darkPalette.setColor(QPalette.ColorGroup.Active, QPalette.Window, QColor(53, 53, 53))
    darkPalette.setColor(QPalette.ColorGroup.Active, QPalette.WindowText, Qt.white)
    darkPalette.setColor(QPalette.ColorGroup.Disabled, QPalette.WindowText, QColor(127, 127, 127))
    darkPalette.setColor(QPalette.ColorGroup.Active, QPalette.Base, QColor(42, 42, 42))
    darkPalette.setColor(QPalette.ColorGroup.Active, QPalette.AlternateBase, QColor(66, 66, 66))
    darkPalette.setColor(QPalette.ColorGroup.Active, QPalette.ToolTipBase, QColor(53, 53, 53))
    darkPalette.setColor(QPalette.ColorGroup.Active, QPalette.ToolTipText, Qt.white)
    darkPalette.setColor(QPalette.ColorGroup.Active, QPalette.Text, Qt.white)
    darkPalette.setColor(QPalette.ColorGroup.Disabled, QPalette.Text, QColor(127, 127, 127))
    darkPalette.setColor(QPalette.ColorGroup.Active, QPalette.Dark, QColor(35, 35, 35))
    darkPalette.setColor(QPalette.ColorGroup.Active, QPalette.Shadow, QColor(20, 20, 20))
    darkPalette.setColor(QPalette.ColorGroup.Active, QPalette.Button, QColor(53, 53, 53))
    darkPalette.setColor(QPalette.ColorGroup.Active, QPalette.ButtonText, Qt.white)
    darkPalette.setColor(QPalette.ColorGroup.Disabled, QPalette.ButtonText, QColor(127, 127, 127))
    darkPalette.setColor(QPalette.ColorGroup.Active, QPalette.BrightText, Qt.red)
    darkPalette.setColor(QPalette.ColorGroup.Active, QPalette.Link, QColor(42, 130, 218))
    darkPalette.setColor(QPalette.ColorGroup.Active, QPalette.Highlight, QColor(42, 130, 218))
    darkPalette.setColor(QPalette.ColorGroup.Disabled, QPalette.Highlight, QColor(80, 80, 80))
    darkPalette.setColor(QPalette.ColorGroup.Active, QPalette.HighlightedText, Qt.white)
    darkPalette.setColor(QPalette.ColorGroup.Disabled, QPalette.HighlightedText, QColor(127, 127, 127))
    darkPalette.setColor(QPalette.ColorGroup.Active, QPalette.PlaceholderText, QColor(127,127,127))
    
    darkPalette.setColor(QPalette.ColorGroup.Inactive, QPalette.Window, QColor(53, 53, 53))
    darkPalette.setColor(QPalette.ColorGroup.Inactive, QPalette.WindowText, Qt.white)
    darkPalette.setColor(QPalette.ColorGroup.Inactive, QPalette.Base, QColor(42, 42, 42))
    darkPalette.setColor(QPalette.ColorGroup.Inactive, QPalette.AlternateBase, QColor(66, 66, 66))
    darkPalette.setColor(QPalette.ColorGroup.Inactive, QPalette.ToolTipBase, QColor(53, 53, 53))
    darkPalette.setColor(QPalette.ColorGroup.Inactive, QPalette.ToolTipText, Qt.white)
    darkPalette.setColor(QPalette.ColorGroup.Inactive, QPalette.Text, Qt.white)
    darkPalette.setColor(QPalette.ColorGroup.Inactive, QPalette.Button, QColor(53, 53, 53))
    darkPalette.setColor(QPalette.ColorGroup.Inactive, QPalette.ButtonText, Qt.white)
    darkPalette.setColor(QPalette.ColorGroup.Inactive, QPalette.Highlight, QColor(42, 130, 218))
    darkPalette.setColor(QPalette.ColorGroup.Inactive, QPalette.HighlightedText, Qt.white)
    darkPalette.setColor(QPalette.ColorGroup.Inactive, QPalette.PlaceholderText, QColor(127,127,127))
    return darkPalette

def kill_tree(process: subprocess.Popen):
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for proc in children:
            try: proc.kill()
            except psutil.Error: pass
        try: parent.kill()
        except psutil.Error: pass
        gone, alive = psutil.wait_procs(children + [parent], timeout=3)
        for p in alive:
            try:
                p.terminate()
                p.wait(timeout=1)
            except psutil.Error: pass
    except psutil.NoSuchProcess: pass
    except Exception as e: print(f"Error in kill_tree: {e}")


def get_user_environment() -> dict[str, str]:
    if sys.platform != "win32":
        return os.environ.copy()
    import ctypes
    from ctypes import wintypes
    advapi32, userenv, kernel32 = ctypes.WinDLL("advapi32"), ctypes.WinDLL("userenv"), ctypes.WinDLL("kernel32")
    TOKEN_QUERY = 0x0008
    OpenProcessToken, CreateEnvironmentBlock, DestroyEnvironmentBlock, GetCurrentProcess, CloseHandle = \
        advapi32.OpenProcessToken, userenv.CreateEnvironmentBlock, userenv.DestroyEnvironmentBlock, \
        kernel32.GetCurrentProcess, kernel32.CloseHandle
    OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    OpenProcessToken.restype = wintypes.BOOL
    CreateEnvironmentBlock.argtypes = [ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.BOOL]
    CreateEnvironmentBlock.restype = wintypes.BOOL
    DestroyEnvironmentBlock.argtypes = [wintypes.LPVOID]
    DestroyEnvironmentBlock.restype = wintypes.BOOL
    GetCurrentProcess.argtypes = []
    GetCurrentProcess.restype = wintypes.HANDLE
    CloseHandle.argtypes = [wintypes.HANDLE]
    CloseHandle.restype = wintypes.BOOL
    token = wintypes.HANDLE()
    if not OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
        print("Warning: Failed to open process token, falling back to os.environ.")
        return os.environ.copy()
    try:
        environment = ctypes.c_void_p()
        if not CreateEnvironmentBlock(ctypes.byref(environment), token, False):
            print("Warning: Failed to create environment block, falling back to os.environ.")
            return os.environ.copy()
        try:
            result, env_ptr, offset = {}, ctypes.cast(environment, ctypes.POINTER(ctypes.c_wchar)), 0
            while True:
                current_string, char_offset = "", offset
                while env_ptr[char_offset] != "\0":
                    current_string += env_ptr[char_offset]
                    char_offset += 1
                offset = char_offset + 1
                if not current_string: break
                try:
                    key, value = current_string.split("=", 1)
                    result[key] = value
                except ValueError: pass
            return result
        finally: DestroyEnvironmentBlock(environment)
    finally: CloseHandle(token)

def get_project_settings_group(project_dir: str) -> str:
    basename = os.path.basename(os.path.normpath(project_dir))
    full_hash = hashlib.md5(project_dir.encode('utf-8')).hexdigest()[:8]
    return f"Project_{basename}_{full_hash}"

# --- PySide6 UI Classes ---
class FeedbackTextEdit(QTextEdit):
    submitted = Signal()
    def __init__(self, parent=None): super().__init__(parent)
    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Return and event.modifiers() == Qt.ControlModifier: self.submitted.emit()
        else: super().keyPressEvent(event)

class LogSignals(QObject):
    append_log = Signal(str)

class FeedbackUI(QMainWindow):
    def __init__(self, project_directory: str, prompt: str):
        super().__init__()
        self.project_directory, self.prompt = project_directory, prompt
        self.process: Optional[subprocess.Popen] = None
        self.log_buffer: List[str] = []
        self.feedback_result: Optional[FeedbackResult] = None
        self.log_signals = LogSignals()
        self.log_signals.append_log.connect(self._append_log_to_gui)
        self.setWindowTitle("Interactive Feedback MCP")
        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            icon_path = os.path.join(script_dir, "images", "feedback.png")
            if os.path.exists(icon_path): self.setWindowIcon(QIcon(icon_path))
        except Exception as e: print(f"Warning: Could not load window icon: {e}")
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.settings = QSettings("InteractiveFeedbackMCP", "InteractiveFeedbackMCP")
        self.settings.beginGroup("MainWindow_General")
        geometry = self.settings.value("geometry")
        if geometry: self.restoreGeometry(geometry)
        else:
            self.resize(800, 600)
            try:
                screen = QApplication.primaryScreen().geometry()
                self.move((screen.width() - 800) // 2, (screen.height() - 600) // 2)
            except AttributeError: print("Warning: Could not get primary screen geometry.")
        state = self.settings.value("windowState")
        if state: self.restoreState(state)
        self.settings.endGroup()
        self.project_group_name = get_project_settings_group(self.project_directory)
        self.settings.beginGroup(self.project_group_name)
        loaded_run_command = self.settings.value("run_command", "", type=str)
        loaded_execute_auto = self.settings.value("execute_automatically", False, type=bool)
        command_section_visible = self.settings.value("commandSectionVisible", False, type=bool)
        self.settings.endGroup()
        self.config: FeedbackConfig = {"run_command": loaded_run_command, "execute_automatically": loaded_execute_auto}
        self._create_ui()
        self.command_group.setVisible(command_section_visible)
        self.toggle_command_button.setText("Hide Command Section" if command_section_visible else "Show Command Section")
        set_dark_title_bar(self, True)
        if self.config.get("execute_automatically", False) and self.config.get("run_command"):
            QTimer.singleShot(100, self._run_command)
        self.feedback_text.setFocus()

    def _format_windows_path(self, path: str) -> str:
        if sys.platform == "win32":
            path = path.replace("/", "\\")
            if len(path) >= 2 and path[1] == ":" and path[0].isalpha(): path = path[0].upper() + path[1:]
        return path

    def _create_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        self.toggle_command_button = QPushButton("Show Command Section")
        self.toggle_command_button.clicked.connect(self._toggle_command_section)
        main_layout.addWidget(self.toggle_command_button)
        self.command_group = QGroupBox("Command")
        command_layout = QVBoxLayout(self.command_group)
        working_dir_label = QLabel(f"Working directory: {self._format_windows_path(self.project_directory)}")
        command_layout.addWidget(working_dir_label)
        command_input_layout = QHBoxLayout()
        self.command_entry = QLineEdit(self.config["run_command"])
        self.command_entry.returnPressed.connect(self._run_command)
        self.command_entry.textChanged.connect(self._update_config_from_ui)
        self.run_button = QPushButton("&Run")
        self.run_button.clicked.connect(self._run_command)
        command_input_layout.addWidget(self.command_entry)
        command_input_layout.addWidget(self.run_button)
        command_layout.addLayout(command_input_layout)
        auto_layout = QHBoxLayout()
        self.auto_check = QCheckBox("Execute automatically on next run")
        self.auto_check.setChecked(self.config.get("execute_automatically", False))
        self.auto_check.stateChanged.connect(self._update_config_from_ui)
        save_button = QPushButton("&Save Configuration")
        save_button.clicked.connect(self._save_config_to_settings)
        auto_layout.addWidget(self.auto_check)
        auto_layout.addStretch()
        auto_layout.addWidget(save_button)
        command_layout.addLayout(auto_layout)
        console_group = QGroupBox("Console")
        console_layout_internal = QVBoxLayout(console_group)
        console_group.setMinimumHeight(150)
        self.log_text_area = QTextEdit()
        self.log_text_area.setReadOnly(True)
        fixed_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        fixed_font.setPointSize(9)
        self.log_text_area.setFont(fixed_font)
        console_layout_internal.addWidget(self.log_text_area)
        button_layout = QHBoxLayout()
        self.clear_button = QPushButton("&Clear Logs")
        self.clear_button.clicked.connect(self.clear_logs_display)
        button_layout.addStretch()
        button_layout.addWidget(self.clear_button)
        console_layout_internal.addLayout(button_layout)
        command_layout.addWidget(console_group)
        self.command_group.setVisible(False)  
        main_layout.addWidget(self.command_group)
        self.feedback_group = QGroupBox("Feedback")
        feedback_layout = QVBoxLayout(self.feedback_group)
        self.description_label = QLabel(self.prompt)
        self.description_label.setWordWrap(True)
        feedback_layout.addWidget(self.description_label)
        self.feedback_text = FeedbackTextEdit()
        self.feedback_text.submitted.connect(self._submit_feedback_and_close)
        font_metrics = self.feedback_text.fontMetrics()
        padding = self.feedback_text.contentsMargins().top() + self.feedback_text.contentsMargins().bottom() + 10
        self.feedback_text.setMinimumHeight(max(5 * font_metrics.height() + padding, 70))
        self.feedback_text.setPlaceholderText("Enter your feedback here (Ctrl+Enter to submit, Esc to cancel)")
        submit_button = QPushButton("&Send Feedback (Ctrl+Enter)")
        submit_button.clicked.connect(self._submit_feedback_and_close)
        feedback_layout.addWidget(self.feedback_text)
        feedback_layout.addWidget(submit_button)
        main_layout.addWidget(self.feedback_group)
        contact_label = QLabel('Need to improve? Contact Fábio Ferreira on <a href="https://x.com/fabiomlferreira">X.com</a> or visit <a href="https://dotcursorrules.com/">dotcursorrules.com</a>')
        contact_label.setOpenExternalLinks(True)
        contact_label.setAlignment(Qt.AlignCenter)
        contact_label.setStyleSheet("font-size: 9pt; color: #cccccc;") 
        main_layout.addWidget(contact_label)
        central_widget.setLayout(main_layout)

    def _toggle_command_section(self):
        is_visible = not self.command_group.isVisible()
        self.command_group.setVisible(is_visible)
        self.toggle_command_button.setText("Hide Command Section" if is_visible else "Show Command Section")
        self.settings.beginGroup(self.project_group_name)
        self.settings.setValue("commandSectionVisible", is_visible)
        self.settings.endGroup()
        self.adjustSize()

    def _update_config_from_ui(self):
        self.config["run_command"] = self.command_entry.text()
        self.config["execute_automatically"] = self.auto_check.isChecked()

    def _append_log_to_gui(self, text: str):
        self.log_buffer.append(text)
        self.log_text_area.append(text.rstrip())
        cursor = self.log_text_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_text_area.setTextCursor(cursor)

    def _check_process_status(self):
        if self.process and self.process.poll() is not None:
            if hasattr(self, 'status_timer') and self.status_timer.isActive(): self.status_timer.stop()
            self._append_log_to_gui(f"\nProcess exited with code {self.process.returncode}\n")
            self.run_button.setText("&Run")
            self.process = None
            self.activateWindow()
            self.feedback_text.setFocus()

    def _run_command(self):
        if self.process:
            self._append_log_to_gui("Stopping current process...\n")
            kill_tree(self.process)
            return
        command_to_run = self.command_entry.text()
        if not command_to_run:
            self._append_log_to_gui("Please enter a command to run.\n")
            return
        self._append_log_to_gui(f"$ {command_to_run}\n")
        self.run_button.setText("Sto&p")
        try:
            self.process = subprocess.Popen(
                command_to_run, shell=True, cwd=self.project_directory,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=get_user_environment(),
                text=True, bufsize=1, encoding="utf-8", errors="ignore")
            # Note: If FeedbackUI runs in a separate process, these threads are fine within that process.
            process_read_stdout_thread = threading.Thread(target=self._read_output_pipe, args=(self.process.stdout,), daemon=True)
            process_read_stdout_thread.start()
            process_read_stderr_thread = threading.Thread(target=self._read_output_pipe, args=(self.process.stderr,), daemon=True)
            process_read_stderr_thread.start()
            
            self.status_timer = QTimer(self)
            self.status_timer.timeout.connect(self._check_process_status)
            self.status_timer.start(200)
        except Exception as e:
            self._append_log_to_gui(f"Error running command: {str(e)}\n")
            self.run_button.setText("&Run")
            self.process = None

    def _read_output_pipe(self, pipe):
        try:
            for line in iter(pipe.readline, ""):
                if line: self.log_signals.append_log.emit(line)
        except Exception as e: self.log_signals.append_log.emit(f"Error reading output: {e}\n")
        finally:
            if pipe: pipe.close()

    def _submit_feedback_and_close(self):
        self.feedback_result = FeedbackResult(
            logs="".join(self.log_buffer),
            interactive_feedback=self.feedback_text.toPlainText().strip())
        self.close()

    def clear_logs_display(self): self.log_text_area.clear()

    def _save_config_to_settings(self):
        self._update_config_from_ui()
        self.settings.beginGroup(self.project_group_name)
        self.settings.setValue("run_command", self.config["run_command"])
        self.settings.setValue("execute_automatically", self.config["execute_automatically"])
        self.settings.endGroup()
        self._append_log_to_gui("Configuration saved for this project.\n")

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Escape and \
           (not self.feedback_text.hasFocus() or not self.feedback_text.toPlainText().strip()):
            self.feedback_result = FeedbackResult(logs="".join(self.log_buffer), interactive_feedback="")
            self.close()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        self.settings.beginGroup("MainWindow_General")
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("windowState", self.saveState())
        self.settings.endGroup()
        self.settings.beginGroup(self.project_group_name)
        self.settings.setValue("commandSectionVisible", self.command_group.isVisible())
        self.settings.endGroup()
        if self.process:
            kill_tree(self.process)
            self.process = None
        if self.feedback_result is None:
            self.feedback_result = FeedbackResult(
                logs="".join(self.log_buffer), interactive_feedback="")
        
        app_instance = QApplication.instance()
        if app_instance:
             # This print now happens within the dedicated GUI process's main thread.
             print(f"DEBUG: Quitting QApplication from FeedbackUI.closeEvent() in process {os.getpid()}, Qt thread {QThread.currentThread()}.")
             app_instance.quit()
        super().closeEvent(event)

# --- Core Function to Run UI (This will run IN THE SEPARATE PROCESS) ---
def execute_feedback_ui_in_process(project_directory: str, prompt: str) -> FeedbackResult:
    # This function is the target for the new process.
    # It will have its own Python interpreter space (mostly) and can create its own QApplication.
    print(f"DEBUG: execute_feedback_ui_in_process called in PID {os.getpid()}, Python thread {threading.get_ident()}, Qt thread {QThread.currentThread()}")
    
    # QApplication *must* be created here, in the main thread of this new process.
    app_for_this_process = QApplication.instance()
    if app_for_this_process is not None:
        # This should ideally not happen if it's a fresh process, but safety check.
        print(f"WARNING: QApplication.instance() already exists in new process {os.getpid()} before creation. This is unexpected. Reusing.")
    else:
        print(f"DEBUG: Creating new QApplication in process {os.getpid()}, Qt thread {QThread.currentThread()}.")
        app_for_this_process = QApplication([])

    if not app_for_this_process:
        # Should not happen if creation is successful.
        critical_error_msg = f"CRITICAL ERROR: QApplication could not be initialized in process {os.getpid()}."
        print(critical_error_msg)
        # This return will be put into the MPQueue by the process_target_for_gui
        return FeedbackResult(logs=critical_error_msg, interactive_feedback="")

    app_for_this_process.setPalette(get_dark_mode_palette(app_for_this_process))
    app_for_this_process.setStyle("Fusion")

    ui_instance = None
    try:
        ui_instance = FeedbackUI(project_directory, prompt)
        ui_instance.show()
        
        print(f"DEBUG: Calling exec() on QApplication in process {os.getpid()}, Qt thread {QThread.currentThread()}.")
        app_for_this_process.exec() 
        print(f"DEBUG: QApplication.exec() finished in process {os.getpid()}, Qt thread {QThread.currentThread()}.")

    except Exception as e_ui:
        error_during_ui = f"Error during UI execution in process {os.getpid()}, Qt thread {QThread.currentThread()}: {e_ui}"
        print(error_during_ui)
        # Log the traceback for better debugging
        import traceback
        tb_str = traceback.format_exc()
        print(tb_str)
        error_during_ui += f"\nTraceback:\n{tb_str}"
        
        log_output = error_during_ui
        if ui_instance and hasattr(ui_instance, 'log_buffer'): # Check if log_buffer exists
             log_output += "\n" + "".join(ui_instance.log_buffer)
        
        # Ensure feedback_result is set on ui_instance if ui_instance exists, even if it's an error one
        if ui_instance:
            ui_instance.feedback_result = FeedbackResult(logs=log_output, interactive_feedback="")
        else: # if ui_instance itself failed to create
             return FeedbackResult(logs=log_output, interactive_feedback="")


    finally:
        # Cleanup UI instance
        if ui_instance:
            # ui_instance.close() # closeEvent already calls quit, which stops exec. Explicit close might be redundant or cause issues if already closing.
            ui_instance.deleteLater() 
            print(f"DEBUG: Scheduled ui_instance.deleteLater() in process {os.getpid()}, Qt thread {QThread.currentThread()}.")
            # Process events to allow deleteLater to occur before process exits
            app_for_this_process.processEvents()


    # Result should be set by FeedbackUI.closeEvent or by the exception handler above
    result = ui_instance.feedback_result if ui_instance and ui_instance.feedback_result is not None else None
    
    if result:
        print(f"DEBUG: UI interaction completed in process {os.getpid()}. Result: Logs - {len(result['logs'])} chars, Feedback - '{result['interactive_feedback']}'")
        return result
    else:
        # This case means feedback_result was None even after normal closure or handled exception.
        # This should be rare if closeEvent and exception handling are correct.
        warning_msg = f"WARNING: UI in process {os.getpid()} closed without providing a result (feedback_result is None after exec). Fallback."
        print(warning_msg)
        # Try to get logs if ui_instance exists
        final_logs = warning_msg
        if ui_instance and hasattr(ui_instance, 'log_buffer'):
            final_logs += "\nCollected Logs:\n" + "".join(ui_instance.log_buffer)

        return FeedbackResult(logs=final_logs, interactive_feedback="")


# --- FastAPI Application ---
app = FastAPI(
    title="Interactive Feedback API",
    description="API to trigger a PySide6 GUI for collecting user feedback.",
    version="1.0.0"
)

class FeedbackRequest(BaseModel):
    project_directory: str
    prompt: str
    server_save_path: Optional[str] = None

class FeedbackResponse(BaseModel):
    logs: str
    interactive_feedback: str


# This function will be the target for the multiprocessing.Process
def process_target_for_gui(project_dir: str, prompt_str: str, result_mp_queue: MPQueue):
    # This function runs in the new process.
    # It calls execute_feedback_ui_in_process which manages its own QApplication specific to this process.
    print(f"DEBUG: process_target_for_gui started in PID {os.getpid()}, Python thread {threading.get_ident()}. About to call Qt logic.")
    try:
        feedback_data = execute_feedback_ui_in_process(
            project_directory=project_dir,
            prompt=prompt_str
        )
        result_mp_queue.put(feedback_data)
    except Exception as e_proc_target:
        # Catch-all for unexpected errors within the process target function itself
        # (though execute_feedback_ui_in_process should also catch its own errors)
        tb_str = traceback.format_exc()
        error_msg = f"CRITICAL ERROR in GUI Process {os.getpid()} (process_target_for_gui): {str(e_proc_target)}\nTraceback:\n{tb_str}"
        print(error_msg)
        result_mp_queue.put(FeedbackResult(logs=error_msg, interactive_feedback=""))
    finally:
        print(f"DEBUG: process_target_for_gui finished in PID {os.getpid()}. Result (or error) placed in MPQueue.")


@app.post("/run_feedback_ui/", response_model=FeedbackResponse)
async def api_trigger_feedback_ui(request: FeedbackRequest):
    # Use multiprocessing.Queue for inter-process communication
    mp_result_queue = MPQueue()

    print(f"DEBUG: FastAPI (PID {os.getpid()}): Received request. Creating GUI process for: {request.project_directory}")
    
    # Create and start the new process
    # Important: On some platforms (like Windows, or macOS with 'spawn' start method), 
    # the target function and its arguments must be picklable. Standard types are fine.
    gui_process = Process(target=process_target_for_gui, args=(
        request.project_directory,
        request.prompt,
        mp_result_queue
    ))
    gui_process.daemon = True # Allows main FastAPI process to exit even if child hangs, though we try to join.
    gui_process.start()
    print(f"DEBUG: FastAPI: Started GUI process {gui_process.pid}")

    final_result = None
    try:
        # Wait for the result from the process queue. Timeout is crucial.
        final_result = mp_result_queue.get(timeout=3600.0) # 1 hour timeout
        print(f"DEBUG: FastAPI: Got result from process queue (PID {gui_process.pid}): Logs len {len(final_result['logs']) if final_result and 'logs' in final_result else -1}")
    except queue.Empty: # This is the correct exception for MPQueue.get(timeout=...)
        print(f"ERROR: FastAPI: GUI interaction (multiprocessing PID {gui_process.pid}) timed out.")
        if gui_process.is_alive():
            print(f"DEBUG: FastAPI: Terminating hung GUI process {gui_process.pid} due to timeout.")
            gui_process.terminate() # Send SIGTERM
            gui_process.join(timeout=5.0) # Wait a bit
            if gui_process.is_alive():
                 print(f"WARNING: FastAPI: GUI process {gui_process.pid} did not terminate after SIGTERM, attempting SIGKILL.")
                 gui_process.kill() # Send SIGKILL
                 gui_process.join(timeout=5.0) # Wait a bit more
        raise HTTPException(status_code=504, detail="GUI interaction timed out.")
    except Exception as e_queue:
        print(f"ERROR: FastAPI: Error retrieving result from process queue (PID {gui_process.pid}): {e_queue}")
        if gui_process.is_alive(): # Clean up process on other errors too
            gui_process.terminate()
            gui_process.join(timeout=5.0)
        raise HTTPException(status_code=500, detail=f"Error processing GUI result: {str(e_queue)}")
    finally:
        # Ensure the process is joined (waited for) to clean up resources,
        # regardless of how the try block exited.
        if gui_process.is_alive():
            print(f"DEBUG: FastAPI: GUI process {gui_process.pid} is still alive after result/exception, joining...")
            gui_process.join(timeout=10.0) # Wait for the process to finish
        
        if gui_process.is_alive(): # If still alive after join attempt
            print(f"WARNING: FastAPI: GUI process {gui_process.pid} did not exit cleanly after join. Terminating forcefully.")
            gui_process.terminate()
            gui_process.join(timeout=5.0)
            if gui_process.is_alive():
                print(f"WARNING: FastAPI: GUI process {gui_process.pid} still alive after terminate. Killing.")
                gui_process.kill()
                gui_process.join(timeout=5.0) # Final wait

        exit_code_msg = f"DEBUG: FastAPI: GUI process {gui_process.pid} finished."
        if hasattr(gui_process, 'exitcode') and gui_process.exitcode is not None:
            exit_code_msg += f" Exit code: {gui_process.exitcode}."
        else:
            exit_code_msg += " Exit code not available or process was killed."
        print(exit_code_msg)
        
        # Close the queue from the parent side to signal no more data will be sent/received
        # and help with resource cleanup.
        mp_result_queue.close()
        mp_result_queue.join_thread() # Wait for the queue's feeder thread to finish


    if final_result is None: 
        # This case should be less likely if process_target_for_gui always puts something.
        raise HTTPException(status_code=500, detail="GUI process did not return a valid result (None received).")
    
    if "CRITICAL ERROR" in final_result.get("logs", "") or "Fatal Qt Error" in final_result.get("logs", ""):
         print(f"ERROR: FastAPI: Critical error reported from GUI process {gui_process.pid if gui_process else 'N/A'}: {final_result['logs']}")

    if request.server_save_path:
        try:
            output_dir = os.path.dirname(request.server_save_path)
            if output_dir: os.makedirs(output_dir, exist_ok=True)
            with open(request.server_save_path, "w", encoding="utf-8") as f:
                json.dump(final_result, f, indent=4)
            print(f"INFO: FastAPI: Feedback result saved to: {request.server_save_path}")
        except Exception as e:
            print(f"WARNING: FastAPI: Could not save feedback result to {request.server_save_path}: {e}")

    return FeedbackResponse(**final_result)


if __name__ == "__main__":
    # Important for multiprocessing on Windows and macOS with 'spawn' start method:
    # The entry point of the script must be protected by `if __name__ == "__main__":`
    # to prevent child processes from re-executing the server setup code.
    
    # For 'fork' start method (default on Linux), this is less critical for Process creation itself,
    # but still good practice for organizing code.
    
    # If you're using a start method other than 'fork' (e.g., 'spawn' or 'forkserver'),
    # you might need to set it explicitly:
    # import multiprocessing as mp
    # mp.set_start_method('spawn', force=True) # if needed, place at very top of script

    print("Starting FastAPI server...")
    # To run the FastAPI server:
    # uvicorn your_script_name:app --host 0.0.0.0 --port 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)

