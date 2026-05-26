# deepseek_dashboard.py
import os
import sys
import sqlite3
from datetime import datetime
from pathlib import Path

import requests
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QProgressBar, QSystemTrayIcon, QMenu,
    QFrame, QGridLayout, QSpacerItem, QSizePolicy, QGraphicsDropShadowEffect
)
from PyQt5.QtCore import Qt, QTimer, QThread, pyqtSignal, QPoint, QPropertyAnimation, QEasingCurve
from PyQt5.QtGui import QFont, QIcon, QPixmap, QPainter, QBrush, QColor, QPainterPath

# ==================== 配置 ====================
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "sk-7791568d54fd4c20a8c90072d81778c5")
DB_PATH = Path.home() / ".deepseek_usage.db"
REFRESH_INTERVAL_MS = 5 * 60 * 1000  # 5分钟
# =============================================

# ------------------ 数据管理（独立线程） ------------------
class DataFetcher(QThread):
    """后台线程获取余额和数据库统计"""
    data_ready = pyqtSignal(dict, dict, dict)  # balance, metrics, cost

    def run(self):
        balance = self.fetch_balance()
        metrics = self.fetch_metrics()
        cost = self.calculate_costs(metrics)
        self.data_ready.emit(balance, metrics, cost)

    def fetch_balance(self):
        url = "https://api.deepseek.com/user/balance"
        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            if data.get("is_available") and data.get("balance_infos"):
                info = data["balance_infos"][0]
                return {
                    "total_balance": float(info.get("total_balance", 0)),
                    "granted_balance": float(info.get("granted_balance", 0)),
                    "topped_up_balance": float(info.get("topped_up_balance", 0))
                }
        except Exception:
            pass
        return {"total_balance": 0, "granted_balance": 0, "topped_up_balance": 0, "error": True}

    def fetch_metrics(self):
        """从本地SQLite查询用量数据（由 deepseek_proxy.py 写入）"""
        return self._fetch_metrics_from_db()

    def _fetch_metrics_from_db(self):
        """从本地SQLite查询用量（兜底）"""
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT,
                input_tokens INTEGER,
                output_tokens INTEGER,
                cache_hit_tokens INTEGER,
                cache_miss_tokens INTEGER,
                total_tokens INTEGER
            )
        """)
        now = datetime.now()
        first_day = datetime(now.year, now.month, 1).strftime("%Y-%m-%d")
        cur = conn.cursor()
        cur.execute("""
            SELECT COUNT(*), SUM(input_tokens), SUM(output_tokens),
                   SUM(cache_hit_tokens), SUM(cache_miss_tokens), SUM(total_tokens)
            FROM usage_log WHERE timestamp >= ?
        """, (first_day,))
        row = cur.fetchone()
        conn.close()
        if not row or row[0] is None:
            return {
                "request_count": 0, "total_input_tokens": 0, "total_output_tokens": 0,
                "total_cache_hit": 0, "total_cache_miss": 0, "total_tokens": 0
            }
        return {
            "request_count": row[0],
            "total_input_tokens": row[1] or 0,
            "total_output_tokens": row[2] or 0,
            "total_cache_hit": row[3] or 0,
            "total_cache_miss": row[4] or 0,
            "total_tokens": row[5] or 0
        }

    def calculate_costs(self, metrics):
        INPUT_PRICE = 2.0
        OUTPUT_PRICE = 8.0
        CACHE_HIT_PRICE = 0.1
        total_all = metrics["total_input_tokens"] + metrics["total_output_tokens"]
        if total_all == 0:
            return {"total_cost_cny": 0, "input_cost": 0, "output_cost": 0, "cache_cost": 0}
        input_cost = metrics["total_input_tokens"] / 1_000_000 * INPUT_PRICE
        output_cost = metrics["total_output_tokens"] / 1_000_000 * OUTPUT_PRICE
        cache_cost = metrics["total_cache_hit"] / 1_000_000 * CACHE_HIT_PRICE
        total = input_cost + output_cost + cache_cost
        return {
            "total_cost_cny": round(total, 4),
            "input_cost": round(input_cost, 4),
            "output_cost": round(output_cost, 4),
            "cache_cost": round(cache_cost, 4)
        }


# ------------------ 主窗口（无边框 + 卡片风格） ------------------
class DashboardWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(800, 640)
        self.drag_pos = None

        self.init_ui()
        self.init_tray()
        self.init_data_refresh()
        self._fetch_in_progress = False

        # 启动后立即刷新一次
        self.refresh_data()

    def init_ui(self):
        # 中心窗口 - 带圆角和阴影的白色背景
        central_widget = QWidget()
        central_widget.setObjectName("central")
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(10)

        # 自定义标题栏
        title_bar = QFrame()
        title_bar.setFixedHeight(40)
        title_bar.setObjectName("titleBar")
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(10, 0, 10, 0)

        title_label = QLabel("DeepSeek API 用量仪表盘")
        title_label.setObjectName("titleLabel")
        title_label.setFont(QFont("Microsoft YaHei", 12, QFont.Bold))

        self.refresh_btn = QPushButton("⟳ 刷新")
        self.refresh_btn.setObjectName("refreshBtn")
        self.refresh_btn.clicked.connect(self.refresh_data)

        self.quit_btn = QPushButton("✕")
        self.quit_btn.setObjectName("closeBtn")
        self.quit_btn.setFixedSize(30, 30)
        self.quit_btn.clicked.connect(self.hide)  # 关闭 → 隐藏到托盘

        title_layout.addWidget(title_label)
        title_layout.addStretch()
        title_layout.addWidget(self.refresh_btn)
        title_layout.addWidget(self.quit_btn)

        # 关闭按钮 → 隐藏到托盘

        # 内容区域：使用网格布局放置三个卡片
        content_widget = QWidget()
        content_layout = QGridLayout(content_widget)
        content_layout.setSpacing(10)

        # 卡片1：余额
        self.balance_card = self.create_card("💰 账户余额", "balance")
        content_layout.addWidget(self.balance_card, 0, 0)

        # 卡片2：用量统计
        self.usage_card = self.create_card("📊 用量统计", "usage")
        content_layout.addWidget(self.usage_card, 0, 1)

        # 卡片3：费用估算
        self.cost_card = self.create_card("💸 本月费用", "cost")
        content_layout.addWidget(self.cost_card, 1, 0, 1, 2)

        content_layout.setRowStretch(0, 1)
        content_layout.setRowStretch(1, 1)
        content_layout.setColumnStretch(0, 1)
        content_layout.setColumnStretch(1, 1)

        main_layout.addWidget(title_bar)
        main_layout.addWidget(content_widget)

        # 状态栏
        status_bar = QFrame()
        status_bar.setObjectName("statusBar")
        status_bar.setFixedHeight(26)
        status_layout = QHBoxLayout(status_bar)
        status_layout.setContentsMargins(10, 0, 10, 0)

        self.status_indicator = QLabel("●")
        self.status_indicator.setObjectName("statusIndicator")
        self.status_label = QLabel("就绪")
        self.status_timestamp = QLabel("--:--:--")
        self.status_timestamp.setObjectName("statusTimestamp")

        status_layout.addWidget(self.status_indicator)
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(QLabel("上次更新:"))
        status_layout.addWidget(self.status_timestamp)

        main_layout.addWidget(status_bar)

        # 应用样式表
        self.setStyleSheet(self.get_stylesheet())

    def create_card(self, title, card_type):
        """创建带标题和内嵌布局的卡片"""
        card = QFrame()
        card.setObjectName(f"card{card_type.capitalize()}")
        card.setFrameShape(QFrame.StyledPanel)
        main_layout = QVBoxLayout(card)
        main_layout.setSpacing(6)

        # 卡片阴影
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(20)
        shadow.setOffset(0, 2)
        shadow.setColor(QColor(0, 0, 0, 25))
        card.setGraphicsEffect(shadow)

        # 标题
        title_label = QLabel(title)
        title_label.setObjectName("cardTitle")
        main_layout.addWidget(title_label)

        # 内容区域（不同卡片内容不同）
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(6)
        main_layout.addWidget(content)

        if card_type == "balance":
            self.balance_amount_label = QLabel("¥ --")
            self.balance_amount_label.setObjectName("bigNumber")
            self.balance_detail_label = QLabel("加载中...")
            self.balance_detail_label.setWordWrap(True)
            content_layout.addWidget(self.balance_amount_label)
            content_layout.addWidget(self.balance_detail_label)
        elif card_type == "usage":
            # ---- 统计模式 ----
            self.usage_stats_widget = QWidget()
            stats_layout = QVBoxLayout(self.usage_stats_widget)
            stats_layout.setSpacing(4)
            self.usage_request_label = QLabel("请求数: --")
            self.usage_input_label = QLabel("输入Token: --")
            self.usage_output_label = QLabel("输出Token: --")
            self.usage_cache_rate_label = QLabel("缓存命中率: --")
            self.cache_progress = QProgressBar()
            self.cache_progress.setRange(0, 100)
            self.cache_progress.setValue(0)
            self.cache_progress.setTextVisible(True)
            self.cache_progress.setFormat("%p%")
            self.output_ratio_label = QLabel("输出占比: --")
            self.output_progress = QProgressBar()
            self.output_progress.setObjectName("outputProgress")
            self.output_progress.setRange(0, 100)
            self.output_progress.setValue(0)
            self.output_progress.setTextVisible(True)
            self.output_progress.setFormat("%p%")
            stats_layout.addWidget(self.usage_request_label)
            stats_layout.addWidget(self.usage_input_label)
            stats_layout.addWidget(self.usage_output_label)
            stats_layout.addWidget(self.usage_cache_rate_label)
            stats_layout.addWidget(self.cache_progress)
            stats_layout.addWidget(self.output_ratio_label)
            stats_layout.addWidget(self.output_progress)
            stats_layout.addStretch()

            # ---- 引导模式 ----
            self.usage_guidance_widget = QFrame()
            self.usage_guidance_widget.setObjectName("guidanceCard")
            guidance_layout = QVBoxLayout(self.usage_guidance_widget)
            guidance_layout.setSpacing(8)
            guidance_title = QLabel("ℹ️ 暂无用量数据")
            guidance_title.setObjectName("guidanceTitle")
            guidance_body = QLabel(
                "本月尚无 API 调用记录。\n\n"
                "启动 deepseek_proxy.py 后，将自动捕获\n"
                "API 调用的 token 用量并显示在此处。\n\n"
                "在终端运行:\n"
                "  python deepseekMonitor/deepseek_proxy.py"
            )
            guidance_body.setObjectName("guidanceBody")
            guidance_body.setWordWrap(True)
            guidance_layout.addWidget(guidance_title)
            guidance_layout.addWidget(guidance_body)
            guidance_layout.addStretch()

            content_layout.addWidget(self.usage_stats_widget)
            content_layout.addWidget(self.usage_guidance_widget)
            self.usage_stats_widget.hide()
            self.usage_guidance_widget.show()

        elif card_type == "cost":
            # ---- 统计模式 ----
            self.cost_stats_widget = QWidget()
            cost_stats_layout = QVBoxLayout(self.cost_stats_widget)
            cost_stats_layout.setSpacing(8)
            self.cost_total_label = QLabel("总额: ¥ --")
            self.cost_total_label.setObjectName("costTotal")
            self.cost_detail_label = QLabel("输入: --\n输出: --\n缓存优惠: --")
            cost_stats_layout.addWidget(self.cost_total_label)
            cost_stats_layout.addWidget(self.cost_detail_label)
            cost_stats_layout.addStretch()

            # ---- 引导模式 ----
            self.cost_guidance_widget = QFrame()
            self.cost_guidance_widget.setObjectName("guidanceCard")
            cost_guidance_layout = QVBoxLayout(self.cost_guidance_widget)
            cost_guidance_layout.setSpacing(8)
            cost_guidance_title = QLabel("ℹ️ 暂无费用数据")
            cost_guidance_title.setObjectName("guidanceTitle")
            cost_guidance_body = QLabel(
                "使用 deepseek_proxy.py 代理 API 请求后，\n"
                "将自动记录 token 用量并显示费用。\n\n"
                "输入: ¥2/百万token\n"
                "输出: ¥8/百万token\n"
                "缓存: ¥0.1/百万token"
            )
            cost_guidance_body.setObjectName("guidanceBody")
            cost_guidance_body.setWordWrap(True)
            cost_guidance_layout.addWidget(cost_guidance_title)
            cost_guidance_layout.addWidget(cost_guidance_body)
            cost_guidance_layout.addStretch()

            content_layout.addWidget(self.cost_stats_widget)
            content_layout.addWidget(self.cost_guidance_widget)
            self.cost_stats_widget.hide()
            self.cost_guidance_widget.show()

        return card

    def update_dashboard(self, balance, metrics, cost):
        """更新所有卡片数据"""
        # 余额
        if "error" in balance:
            self.balance_amount_label.setText("⚠️ 获取失败")
            self.balance_amount_label.setStyleSheet("color: #e74c3c; font-size: 36px; font-weight: bold; padding: 5px 0px;")
            self.balance_detail_label.setText("请检查网络连接或 API Key 是否有效")
            self.balance_detail_label.setStyleSheet("color: #e74c3c;")
        else:
            self.balance_amount_label.setStyleSheet("")
            self.balance_detail_label.setStyleSheet("")
            total = balance.get("total_balance", 0)
            self.balance_amount_label.setText(f"¥ {total:.2f}")
            detail = f"总余额: {total:.2f} 元\n赠送: {balance['granted_balance']:.2f} 元\n充值: {balance['topped_up_balance']:.2f} 元"
            self.balance_detail_label.setText(detail)

        # 用量
        req = metrics.get("request_count", 0)
        if req == 0:
            self.usage_stats_widget.hide()
            self.usage_guidance_widget.show()
            self.cost_stats_widget.hide()
            self.cost_guidance_widget.show()
        else:
            self.usage_guidance_widget.hide()
            self.usage_stats_widget.show()
            self.cost_guidance_widget.hide()
            self.cost_stats_widget.show()

            inp = metrics.get("total_input_tokens", 0)
            out = metrics.get("total_output_tokens", 0)
            total_tokens = metrics.get("total_tokens", 0)
            cache_hit = metrics.get("total_cache_hit", 0)
            cache_miss = metrics.get("total_cache_miss", 0)
            hit_rate = (cache_hit / (cache_hit + cache_miss) * 100) if (cache_hit + cache_miss) > 0 else 0
            output_pct = (out / total_tokens * 100) if total_tokens > 0 else 0

            self.usage_request_label.setText(f"📌 请求数: {req}")
            self.usage_input_label.setText(f"📥 输入Token: {inp:,}")
            self.usage_output_label.setText(f"📤 输出Token: {out:,}")
            self.usage_cache_rate_label.setText(f"💾 缓存命中率: {hit_rate:.1f}%")
            self.cache_progress.setValue(int(hit_rate))
            self.output_ratio_label.setText(f"📤 输出占比: {output_pct:.1f}%")
            self.output_progress.setValue(int(output_pct))

            # 费用
            total_cost = cost.get("total_cost_cny", 0)
            self.cost_total_label.setText(f"💰 总额: ¥ {total_cost:.2f}")
            detail = f"输入费用: ¥ {cost.get('input_cost',0):.4f}\n输出费用: ¥ {cost.get('output_cost',0):.4f}\n缓存抵扣: ¥ {cost.get('cache_cost',0):.4f}"
            self.cost_detail_label.setText(detail)

    def _update_status_bar(self, state="idle", timestamp=None, status_text=None):
        """更新状态栏指示器和文本"""
        colors = {"idle": "#a0aec0", "loading": "#e67e22", "success": "#27ae60", "error": "#e74c3c"}
        labels = {"idle": "就绪", "loading": "正在刷新...", "success": "刷新成功", "error": "请求失败"}
        self.status_indicator.setStyleSheet(f"color: {colors.get(state, '#a0aec0')}; font-size: 14px;")
        self.status_label.setText(status_text or labels.get(state, ""))
        if timestamp:
            self.status_timestamp.setText(timestamp)

    # ------------------ 数据刷新（后台线程） ------------------
    def init_data_refresh(self):
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_data)
        self.refresh_timer.start(REFRESH_INTERVAL_MS)

    def refresh_data(self):
        """启动后台线程拉取数据"""
        if self._fetch_in_progress:
            return
        self._fetch_in_progress = True
        self.refresh_btn.setEnabled(False)
        self.refresh_btn.setText("⏳ 刷新中...")
        self._update_status_bar(state="loading")
        self.fetcher = DataFetcher()
        self.fetcher.data_ready.connect(self.on_data_ready)
        self.fetcher.finished.connect(self._on_fetcher_exit)
        self.fetcher.start()

    def _on_fetcher_exit(self):
        self._fetch_in_progress = False

    def on_data_ready(self, balance, metrics, cost):
        self._fetch_in_progress = False
        self.update_dashboard(balance, metrics, cost)
        self.refresh_btn.setEnabled(True)
        self.refresh_btn.setText("⟳ 刷新")
        now_str = datetime.now().strftime("%H:%M:%S")
        if "error" not in balance:
            self._update_status_bar(state="success", timestamp=now_str, status_text="刷新成功")
            self.tray_icon.setToolTip(f"DeepSeek 余额: ¥ {balance['total_balance']:.2f}")
        else:
            self._update_status_bar(state="error", timestamp=now_str)
            self.tray_icon.setToolTip("DeepSeek 余额获取失败")

    # ------------------ 托盘图标 ------------------
    def init_tray(self):
        self.tray_icon = QSystemTrayIcon(self)
        pixmap = self.create_tray_icon()
        self.tray_icon.setIcon(QIcon(pixmap))
        self.tray_icon.setToolTip("DeepSeek 监控")

        tray_menu = QMenu()
        show_action = tray_menu.addAction("📊 显示主窗口")
        show_action.triggered.connect(self.show_normal)
        refresh_action = tray_menu.addAction("🔄 刷新数据")
        refresh_action.triggered.connect(self.refresh_data)
        quit_action = tray_menu.addAction("🚪 退出")
        quit_action.triggered.connect(self.quit_app)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_click)
        self.tray_icon.show()

    def create_tray_icon(self):
        """加载当前目录下的图标文件"""
        icon_path = Path(__file__).parent / "deepseek-blue.png"
        if icon_path.exists():
            return QPixmap(str(icon_path))
        # 兜底：生成一个简单的蓝色图标
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        painter.setBrush(QColor(0, 120, 215))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(16, 16, 32, 32)
        painter.drawRect(28, 48, 8, 8)
        painter.end()
        return pixmap

    def on_tray_click(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self.show_normal()

    def show_normal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    # ------------------ 无边框窗口拖拽 ------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton and self.drag_pos is not None:
            self.move(event.globalPos() - self.drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_pos = None

    def quit_app(self):
        self.tray_icon.hide()
        QApplication.quit()

    # ------------------ 样式表（优美现代） ------------------
    def get_stylesheet(self):
        return """
        QWidget#central {
            background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                stop:0 #f8fafc, stop:1 #eef2f7);
            border-radius: 16px;
        }
        QFrame#cardBalance, QFrame#cardUsage, QFrame#cardCost {
            background-color: white;
            border-radius: 12px;
            padding: 12px;
            margin: 3px;
        }
        QFrame#cardBalance {
            border-left: 4px solid #0078d7;
        }
        QFrame#cardUsage {
            border-left: 4px solid #6c5ce7;
        }
        QFrame#cardCost {
            border-left: 4px solid #e67e22;
        }
        QFrame#titleBar {
            background-color: transparent;
        }
        QLabel#titleLabel {
            color: #2c3e50;
        }
        QLabel#cardTitle {
            font-size: 16px;
            font-weight: bold;
            color: #2c3e50;
            border-bottom: 2px solid #e2e8f0;
            padding-bottom: 6px;
        }
        QLabel#bigNumber {
            font-size: 36px;
            font-weight: bold;
            color: #0078d7;
            padding: 5px 0px;
        }
        QLabel#costTotal {
            font-size: 24px;
            font-weight: bold;
            color: #e67e22;
            padding: 5px 0px;
        }
        QProgressBar {
            border: none;
            background-color: #edf2f7;
            border-radius: 4px;
            height: 8px;
            text-align: center;
            font-size: 10px;
        }
        QProgressBar::chunk {
            border-radius: 4px;
            background-color: #6c5ce7;
        }
        QProgressBar#outputProgress::chunk {
            border-radius: 4px;
            background-color: #0078d7;
        }
        QPushButton#refreshBtn {
            background-color: #0078d7;
            color: white;
            border: none;
            border-radius: 6px;
            padding: 5px 12px;
            font-weight: bold;
        }
        QPushButton#refreshBtn:hover {
            background-color: #106ebe;
        }
        QPushButton#refreshBtn:disabled {
            background-color: #a0aec0;
        }
        QPushButton#closeBtn {
            background-color: #e74c3c;
            color: white;
            border: none;
            border-radius: 15px;
            font-weight: bold;
        }
        QPushButton#closeBtn:hover {
            background-color: #c0392b;
        }
        QLabel {
            font-family: "Microsoft YaHei";
            font-size: 12px;
            color: #4a5568;
        }
        QFrame#statusBar {
            background-color: #f8fafc;
            border: 1px solid #e2e8f0;
            border-radius: 8px;
        }
        QLabel#statusIndicator {
            font-size: 14px;
        }
        QLabel#statusTimestamp {
            color: #718096;
            font-size: 11px;
        }
        QLabel#guidanceTitle {
            font-size: 14px;
            font-weight: bold;
            color: #4a5568;
            padding: 5px 0px;
        }
        QLabel#guidanceBody {
            font-size: 11px;
            color: #718096;
            line-height: 1.5;
        }
        QFrame#guidanceCard {
            background-color: #f7fafc;
            border: 1px dashed #cbd5e0;
            border-radius: 8px;
            padding: 10px;
        }
        """


# ------------------ 启动应用程序 ------------------
def main():
    if DEEPSEEK_API_KEY == "你的API密钥":
        print("❌ 请在脚本中设置正确的 DEEPSEEK_API_KEY，或配置环境变量。")
        sys.exit(1)

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    window = DashboardWindow()
    # 默认隐藏到托盘，点击托盘图标再显示
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()