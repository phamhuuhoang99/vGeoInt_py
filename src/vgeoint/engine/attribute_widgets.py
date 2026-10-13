"""Port of AircraftAttributeWidget.cpp, ShipAttributeWidget.cpp, TankAttributeWidget.cpp and RocketAttributeWidget.cpp."""

from qgis.PyQt.QtWidgets import QWidget

from vgeoint.common.ui import load_ui_class


class AircraftAttributeWidget(QWidget, load_ui_class("engine", "AircraftAttributeWidget")):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

    def view(self, aircraft):
        self.tenLed.setText(aircraft.name())
        self.chieuDaiDspb.setValue(aircraft.chieu_dai_than)
        self.saiCanhDspb.setValue(aircraft.sai_canh)
        self.chieuCaoDspb.setValue(aircraft.chieu_cao)
        self.dongCoLed.setText(aircraft.dong_co)
        self.vmaxDspb.setValue(aircraft.vmax)
        self.hmaxDspb.setValue(aircraft.hmax)
        self.tambayMaxDspb.setValue(aircraft.tam_bay_max)
        self.banKinhDspb.setValue(aircraft.ban_kinh_hd)
        self.nuocSxLed.setText(aircraft.nuoc_sx)

    def get_attrib(self, aircraft):
        aircraft.chieu_dai_than = self.chieuDaiDspb.value()
        aircraft.sai_canh = self.saiCanhDspb.value()
        aircraft.chieu_cao = self.chieuCaoDspb.value()
        aircraft.dong_co = self.dongCoLed.text().strip()
        aircraft.vmax = self.vmaxDspb.value()
        aircraft.hmax = self.hmaxDspb.value()
        aircraft.tam_bay_max = self.tambayMaxDspb.value()
        aircraft.ban_kinh_hd = self.banKinhDspb.value()
        aircraft.nuoc_sx = self.nuocSxLed.text().strip()

    def setEnabled(self, enabled: bool):  # noqa: N802 - hides QWidget.setEnabled like the C++ class
        for w in (
            self.tenLed, self.chieuDaiDspb, self.saiCanhDspb, self.chieuCaoDspb, self.dongCoLed,
            self.vmaxDspb, self.hmaxDspb, self.tambayMaxDspb, self.banKinhDspb, self.nuocSxLed,
        ):
            w.setEnabled(enabled)


class ShipAttributeWidget(QWidget, load_ui_class("engine", "ShipAttributeWidget")):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

    def view(self, ship):
        self.tenLed.setText(ship.name())
        self.chieuDaiDspb.setValue(ship.chieu_dai)
        self.chieuRongDspb.setValue(ship.chieu_rong)
        self.momNuocDspb.setValue(ship.mom_nuoc)
        self.taiTrongDspb.setValue(ship.tai_trong)
        self.dongCoLed.setText(ship.dong_co)
        self.chanVitSpb.setValue(ship.chan_vit)
        self.congSuatSpb.setValue(ship.cong_suat)
        self.tocDoDspb.setValue(ship.toc_do)
        self.tamHoatDongDspb.setValue(ship.tam_hoat_dong)
        self.thuyThuDoanSpb.setValue(ship.thuy_thu_doan)
        self.nuocSoHuuLed.setText(ship.nuoc_so_huu)

    def get_attrib(self, ship):
        ship.chieu_dai = self.chieuDaiDspb.value()
        ship.chieu_rong = self.chieuRongDspb.value()
        ship.mom_nuoc = self.momNuocDspb.value()
        ship.tai_trong = self.taiTrongDspb.value()
        ship.dong_co = self.dongCoLed.text()
        ship.chan_vit = self.chanVitSpb.value()
        ship.cong_suat = self.congSuatSpb.value()
        ship.toc_do = self.tocDoDspb.value()
        ship.tam_hoat_dong = self.tamHoatDongDspb.value()
        ship.thuy_thu_doan = self.thuyThuDoanSpb.value()
        ship.nuoc_so_huu = self.nuocSoHuuLed.text()

    def setEnabled(self, enabled: bool):  # noqa: N802
        # C++ không khóa tenLed ở đây (khác các widget còn lại)
        for w in (
            self.chieuDaiDspb, self.chieuRongDspb, self.momNuocDspb, self.taiTrongDspb, self.dongCoLed,
            self.chanVitSpb, self.congSuatSpb, self.tocDoDspb, self.tamHoatDongDspb, self.thuyThuDoanSpb,
            self.nuocSoHuuLed,
        ):
            w.setEnabled(enabled)


class TankAttributeWidget(QWidget, load_ui_class("engine", "TankAttributeWidget")):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

    def view(self, tank):
        self.tenLed.setText(tank.name())
        self.chieuDaiDspb.setValue(tank.chieu_dai)
        self.chieuRongDspb.setValue(tank.chieu_rong)
        self.taiTrongDspb.setValue(tank.tai_trong)
        self.nuocSoHuuLed.setText(tank.nuoc_so_huu)

    def get_attrib(self, tank):
        tank.chieu_dai = self.chieuDaiDspb.value()
        tank.chieu_rong = self.chieuRongDspb.value()
        tank.tai_trong = self.taiTrongDspb.value()
        tank.nuoc_so_huu = self.nuocSoHuuLed.text().strip()

    def setEnabled(self, enabled: bool):  # noqa: N802
        for w in (self.tenLed, self.chieuDaiDspb, self.chieuRongDspb, self.taiTrongDspb, self.nuocSoHuuLed):
            w.setEnabled(enabled)


class RocketAttributeWidget(QWidget, load_ui_class("engine", "RocketAttributeWidget")):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)

    def view(self, rocket):
        self.tenLed.setText(rocket.name())
        self.soBeSpb.setValue(rocket.so_be)
        self.soXeRadaSpb.setValue(rocket.so_xe_rada)
        self.soXeChiHuySpb.setValue(rocket.so_xe_chi_huy)
        self.duongKinhDspb.setValue(rocket.duong_kinh)
        self.nuocSoHuuLed.setText(rocket.nuoc_so_huu)

    def get_attrib(self, rocket):
        rocket.so_be = self.soBeSpb.value()
        rocket.so_xe_rada = self.soXeRadaSpb.value()
        rocket.so_xe_chi_huy = self.soXeChiHuySpb.value()
        rocket.duong_kinh = self.duongKinhDspb.value()
        rocket.nuoc_so_huu = self.nuocSoHuuLed.text()

    def setEnabled(self, enabled: bool):  # noqa: N802
        for w in (self.tenLed, self.soBeSpb, self.soXeRadaSpb, self.soXeChiHuySpb, self.duongKinhDspb, self.nuocSoHuuLed):
            w.setEnabled(enabled)
