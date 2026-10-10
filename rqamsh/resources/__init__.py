"""供 Python 与 CLI 共用的同步资源操作及统一注册表。"""

from ._base import _Resource
from .workspaces import Workspaces
from .products import Products, ProductGroups
from .tags import Tags
from .balances import Balances
from .custom_instruments import CustomInstruments
from .trades import Trades
from .valuation_reports import ValuationReports
from .asset_units import AssetUnits, PositionsStatements
from .reconciliation import Reconciliation
from .custodian_events import CustodianEvents
from .unit_events import UnitEvents
from .positions_sheets import PositionsSheets
from .confirmations import Confirmations
from .permissions import Permissions
from .analytics import Analytics
from .risk_monitor import RiskMonitor
from .market_data import MarketData


RESOURCE_CLASSES: dict[str, type[_Resource]] = {
    "workspaces": Workspaces,
    "products": Products,
    "product_groups": ProductGroups,
    "tags": Tags,
    "custom_instruments": CustomInstruments,
    "balances": Balances,
    "trades": Trades,
    "valuation_reports": ValuationReports,
    "asset_units": AssetUnits,
    "positions_statements": PositionsStatements,
    "reconciliation": Reconciliation,
    "custodian_events": CustodianEvents,
    "unit_events": UnitEvents,
    "positions_sheets": PositionsSheets,
    "confirmations": Confirmations,
    "permissions": Permissions,
    "analytics": Analytics,
    "risk_monitor": RiskMonitor,
    "market_data": MarketData,
}
