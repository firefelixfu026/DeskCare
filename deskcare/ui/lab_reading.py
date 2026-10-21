"""Separate report-reading workspace; originals and drafts stay on this machine."""
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QHeaderView, QLabel,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSpinBox, QSplitter,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from deskcare.domain.lab_reading import LabRow, STATUS, parse_lab_text
from deskcare.ui.choices import SoftComboBox
from deskcare.importers.lab_source import LabSourceError, read_selected_lab_source
from deskcare.services.reminder_advice import AdviceError


class _LabWorker(QObject):
    finished = Signal(object, str)

    def __init__(self, action):
        super().__init__()
        self.action = action

    @Slot()
    def run(self):
        try:
            self.finished.emit(self.action(), "")
        except (LabSourceError, AdviceError, ValueError) as exc:
            self.finished.emit(None, str(exc))
        except Exception:
            self.finished.emit(None, "本次处理未完成。可以手动核对，本机说明不受 AI 故障影响。")
        finally:
            self.action = None


class LabReadingDialog(QDialog):
    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._thread = self._worker = None
        self._generation = 0
        self._selected = None
        self.setWindowTitle("检验单辅助阅读")
        self.setMinimumSize(820, 560)
        self.resize(1000, 760)
        root = QVBoxLayout(self)
        title = QLabel("读懂指标，准备好要问医生的问题")
        title.setObjectName("cardTitle")
        root.addWidget(title)
        intro = QLabel("首版支持血常规 6 项常见指标。先对照原件核对，再看说明；不判断疾病，不推荐治疗。")
        intro.setWordWrap(True)
        root.addWidget(intro)
        self.local_consent = QCheckBox("允许在本机处理我主动选择的检验单（独立授权）")
        self.local_consent.setObjectName("aiConsent")
        self.local_consent.toggled.connect(self._local_changed)
        root.addWidget(self.local_consent)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        source = QWidget()
        layout = QVBoxLayout(source)
        bar = QHBoxLayout()
        self.choose = QPushButton("选择 PDF／图片／文字")
        self.choose.clicked.connect(self._choose)
        bar.addWidget(self.choose)
        bar.addStretch()
        bar.addWidget(QLabel("PDF 页码"))
        self.page = QSpinBox()
        self.page.setRange(1, 1)
        self.page.setSuffix(" 页")
        bar.addWidget(self.page)
        self.load_page = QPushButton("读取此页")
        self.load_page.setObjectName("secondaryButton")
        self.load_page.clicked.connect(self._read_page)
        bar.addWidget(self.load_page)
        layout.addLayout(bar)
        split = QSplitter()
        self.image = QLabel("原页预览\n也可以直接在右侧粘贴指标文字。")
        self.image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.image.setTextFormat(Qt.TextFormat.PlainText)
        scroll = QScrollArea()
        scroll.setWidget(self.image)
        scroll.setWidgetResizable(True)
        split.addWidget(scroll)
        self.raw = QPlainTextEdit()
        self.raw.setPlaceholderText("逐行粘贴：项目　结果　单位　报告参考范围\n例如：WBC 6.2 10^9/L 3.5-9.5\n示例不是你的正常值标准，必须使用原报告范围。")
        self.raw.textChanged.connect(self._raw_changed)
        split.addWidget(self.raw)
        split.setSizes([420, 480])
        layout.addWidget(split, 1)
        self.extract_note = QLabel("本机提取可能漏字或列错位。未识别项可在下一页手动添加。一次最多 10 页、8 MB。")
        self.extract_note.setWordWrap(True)
        layout.addWidget(self.extract_note)
        self.parse = QPushButton("从这页文字整理指标 →")
        self.parse.clicked.connect(self._parse)
        layout.addWidget(self.parse)
        self.tabs.addTab(source, "1　原件与文字")
        verify = QWidget()
        layout = QVBoxLayout(verify)
        label = QLabel("逐项检查项目、结果、单位和原报告范围，再勾选“已核对”。修改任一字段后需要重新勾选。")
        label.setWordWrap(True)
        layout.addWidget(label)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["已核对", "项目", "结果", "单位", "报告参考范围", "对照"])
        self.table.verticalHeader().hide()
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setMinimumSectionSize(72)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.verticalHeader().setDefaultSectionSize(48)
        self.table.itemChanged.connect(self._item_changed)
        layout.addWidget(self.table, 1)
        bar = QHBoxLayout()
        add = QPushButton("手动添加指标")
        add.setObjectName("secondaryButton")
        add.clicked.connect(lambda: self.add_row(LabRow("", "", "", "")))
        bar.addWidget(add)
        remove = QPushButton("移除选中项")
        remove.setObjectName("secondaryButton")
        remove.clicked.connect(self._remove)
        bar.addWidget(remove)
        bar.addStretch()
        self.read = QPushButton("查看本机辅助说明 →")
        self.read.clicked.connect(self.show_reading)
        bar.addWidget(self.read)
        layout.addLayout(bar)
        self.tabs.addTab(verify, "2　逐项核对")
        result = QWidget()
        layout = QVBoxLayout(result)
        self.reading = QPlainTextEdit()
        self.reading.setReadOnly(True)
        self.reading.setPlaceholderText("核对完成后，本机即可展示指标含义、报告范围对照和就诊问题。无需 AI。")
        layout.addWidget(self.reading, 1)
        self.ai_consent = QCheckBox("允许 AI 处理本次核对的指标（另外授权，每次发送前确认）")
        self.ai_consent.setObjectName("aiConsent")
        self.ai_consent.toggled.connect(self._ai_changed)
        layout.addWidget(self.ai_consent)
        bar = QHBoxLayout()
        self.provider = SoftComboBox()
        self.provider.addItem("本机 AI", "local")
        self.provider.addItem("联网 AI", "cloud")
        if not service.gateway.local_ai or not service.gateway.local_ai.enabled:
            self.provider.setCurrentIndex(1)
        self.provider.currentIndexChanged.connect(self._invalidate)
        bar.addWidget(self.provider)
        self.ask = QPushButton("AI 帮我整理阅读重点和提问")
        self.ask.clicked.connect(self._ask)
        bar.addWidget(self.ask)
        bar.addStretch()
        layout.addLayout(bar)
        self.tabs.addTab(result, "3　辅助阅读")
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.status)
        footer = QHBoxLayout()
        note = QLabel("不保存报告历史。关闭会清空本次内容；原文件不会修改。扫描页可能产生临时图片，正常结束后清理。")
        note.setWordWrap(True)
        footer.addWidget(note, 1)
        clear = QPushButton("清空本次")
        clear.setObjectName("secondaryButton")
        clear.clicked.connect(self.clear_session)
        footer.addWidget(clear)
        done = QPushButton("关闭")
        done.setObjectName("secondaryButton")
        done.clicked.connect(self.reject)
        footer.addWidget(done)
        root.addLayout(footer)
        self.begin_state()

    def begin_state(self):
        for widget, enabled in ((self.local_consent, self.service.enabled), (self.ai_consent, self.service.ai_enabled)):
            widget.blockSignals(True)
            widget.setChecked(enabled)
            widget.blockSignals(False)
        self.tabs.setEnabled(self.service.enabled)
        self.status.setText("原件和草稿只在本次窗口使用，不会自动上传。")

    def begin(self):
        self.begin_state()
        self.show()
        self.raise_()
        self.activateWindow()

    def _local_changed(self, checked):
        if checked and QMessageBox.question(self, "本机处理授权", "只读取你选择的文件，在本机提取并展示可能敏感的检验结果。\n不保存报告历史、不上传原件。是否开启？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            self.local_consent.blockSignals(True)
            self.local_consent.setChecked(False)
            self.local_consent.blockSignals(False)
            return
        self.service.set_enabled(checked)
        self.clear_session()
        self.begin_state()

    def _ai_changed(self, checked):
        if checked and QMessageBox.question(self, "检验单 AI 单独授权", "AI 只整理阅读重点和就诊问题，不给诊断。\n联网时核对的指标会离开本机，仍属敏感信息，可能产生费用或被服务商保留；每次先预览再确认。是否允许？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            self.ai_consent.blockSignals(True)
            self.ai_consent.setChecked(False)
            self.ai_consent.blockSignals(False)
            return
        self.service.set_ai_enabled(checked)
        self.reading.clear()

    def _invalidate(self, *_):
        self.service.invalidate()
        self.reading.clear()

    def _raw_changed(self):
        # Old confirmations must not survive replacement of their source text.
        self._invalidate()
        self.table.blockSignals(True)
        for index in range(self.table.rowCount()):
            self.table.item(index, 0).setCheckState(Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self._update_checks()

    def clear_session(self):
        self._generation += 1
        self.service.clear()
        self._selected = None
        self.raw.clear()
        self.table.setRowCount(0)
        self.reading.clear()
        self.image.clear()
        self.image.setText("原页预览")
        self.page.setRange(1, 1)
        self.status.setText("本次内容已清空。原文件未修改。")

    def _choose(self):
        if not self.service.enabled or self._thread is not None:
            return
        path, _ = QFileDialog.getOpenFileName(self, "选择一份检验单", "", "检验单 (*.pdf *.png *.jpg *.jpeg *.bmp *.txt *.csv)")
        if path:
            self.clear_session()
            self._selected = path
            self._read_page()

    def _read_page(self):
        if not self.service.enabled or not self._selected or self._thread is not None:
            return
        path, page = self._selected, self.page.value()-1
        self.clear_session()
        self._selected = path
        self._start(lambda: read_selected_lab_source(path, page), self._source_done)

    def _source_done(self, source):
        self.raw.setPlainText(source.text)
        self.page.setRange(1, source.page_count)
        self.page.setValue(source.page+1)
        if source.preview is not None and not source.preview.isNull():
            pixmap = QPixmap.fromImage(source.preview)
            self.image.setPixmap(pixmap.scaledToWidth(430, Qt.TransformationMode.SmoothTransformation))
        self.extract_note.setText(source.method + "。请对照原件逐项核对；列错位时可直接手动录入。")
        self.status.setText("已在本机读取这一页，尚未上传，也未核对。")

    def _parse(self):
        if self.table.rowCount() and QMessageBox.question(self, "替换当前指标草稿？", "重新整理将替换当前表格和核对状态。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            rows, unmatched = parse_lab_text(self.raw.toPlainText())
            self.table.setRowCount(0)
            for row in rows:
                self.add_row(row)
            self._invalidate()
            self.tabs.setCurrentIndex(1)
            self.status.setText(f"整理出 {len(rows)} 项，均未核对。另有 {unmatched} 行含数字但未识别；请回看原件，必要时手动补项。")
        except ValueError as exc:
            self.status.setText(str(exc))

    def add_row(self, row):
        if self.table.rowCount() >= 40:
            self.status.setText("一次最多 40 项，请分次核对。")
            return
        self.table.blockSignals(True)
        index = self.table.rowCount()
        self.table.insertRow(index)
        item = QTableWidgetItem()
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(Qt.CheckState.Checked if row.confirmed else Qt.CheckState.Unchecked)
        self.table.setItem(index, 0, item)
        for column, value in enumerate((row.name, row.result, row.unit, row.reference), 1):
            self.table.setItem(index, column, QTableWidgetItem(value))
        state = QTableWidgetItem()
        state.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        self.table.setItem(index, 5, state)
        self.table.blockSignals(False)
        self._invalidate()
        self._update_checks()

    def _rows(self):
        return tuple(LabRow(*(self.table.item(i, j).text() for j in range(1, 5)),
                            self.table.item(i, 0).checkState() == Qt.CheckState.Checked)
                     for i in range(self.table.rowCount()))

    def _update_checks(self):
        self.table.blockSignals(True)
        for i, row in enumerate(self._rows()):
            state, note = row.check()
            self.table.item(i, 5).setText(STATUS[state])
            self.table.item(i, 5).setToolTip(note)
        self.table.blockSignals(False)

    def _item_changed(self, item):
        self.table.blockSignals(True)
        if 1 <= item.column() <= 4:
            self.table.item(item.row(), 0).setCheckState(Qt.CheckState.Unchecked)
        self.table.blockSignals(False)
        self._invalidate()
        self._update_checks()

    def _remove(self):
        for index in sorted({item.row() for item in self.table.selectedItems()}, reverse=True):
            self.table.removeRow(index)
        self._invalidate()

    def show_reading(self):
        try:
            self.service.replace_rows(self._rows())
            self.reading.setPlainText(self.service.local_reading())
            self.tabs.setCurrentIndex(2)
            self.status.setText("这是本机范围对照与一般知识说明；没有发送数据，也没有作疾病判断。")
        except (ValueError, AdviceError) as exc:
            self.status.setText(str(exc))

    def _ask(self):
        if self._thread is not None:
            return
        try:
            self.service.replace_rows(self._rows())
            request = self.service.prepare(self.provider.currentData())
        except (ValueError, AdviceError) as exc:
            self.status.setText(str(exc))
            return
        preview = QDialog(self)
        preview.setWindowTitle("核对这次要给 AI 的指标")
        preview.resize(680, 520)
        layout = QVBoxLayout(preview)
        target = QLabel(f"服务：{request.endpoint}\n模型：{request.model}")
        target.setTextFormat(Qt.TextFormat.PlainText)
        target.setWordWrap(True)
        layout.addWidget(target)
        text = QPlainTextEdit(request.human_preview())
        text.setReadOnly(True)
        layout.addWidget(text, 1)
        bar = QHBoxLayout()
        cancel = QPushButton("不发送")
        cancel.setObjectName("secondaryButton")
        cancel.clicked.connect(preview.reject)
        bar.addWidget(cancel)
        send = QPushButton("确认发送并整理")
        send.clicked.connect(preview.accept)
        bar.addWidget(send)
        layout.addLayout(bar)
        if preview.exec() == QDialog.DialogCode.Accepted:
            self._start(lambda: self.service.analyze(request, confirmed=True), self._ai_done)

    def _ai_done(self, text):
        self.reading.setPlainText(text)
        self.tabs.setCurrentIndex(2)
        self.status.setText("AI 仅选择阅读重点和提问；指标事实、解释与对照没有交给模型改写。")

    def _start(self, action, callback):
        self._work_generation, self._callback = self._generation, callback
        self._work_revision = self.service.revision
        self.status.setText("正在本机读取…" if callback == self._source_done else "正在整理阅读重点…本机说明仍可用。")
        self.choose.setEnabled(False)
        self.load_page.setEnabled(False)
        self.ask.setEnabled(False)
        self._thread = QThread(self)
        self._worker = _LabWorker(action)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)

        self._worker.finished.connect(self._work_complete)
        self._worker.finished.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._finished)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    @Slot(object, str)
    def _work_complete(self, value, error):
        if self._work_generation != self._generation or not self.service.enabled:
            return
        if self._work_revision != self.service.revision:
            self.status.setText("处理期间内容或授权发生变化，旧结果未显示。请重新核对。")
            return
        if error:
            self.status.setText(error)
        else:
            self._callback(value)

    def _finished(self):
        self._worker = self._thread = None
        self._callback = None
        self.choose.setEnabled(True)
        self.load_page.setEnabled(True)
        self.ask.setEnabled(True)

    def done(self, result):
        self.clear_session()
        super().done(result)
