from PySide6.QtCore import QObject, Signal


class SignalBus(QObject):
    """Signal bus"""

    switchToCard = Signal(str)
    configChanged = Signal(str, str)
    runStatusChanged = Signal(dict)
    deviceConnected = Signal()


signalBus = SignalBus()
