from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from flask import Blueprint, Request, Response, request as flask_request
from flask_restful import Resource
from marshmallow import Schema
from marshmallow.utils import missing
from typing_extensions import Literal
from webargs.flaskparser import parser, use_kwargs
from webargs.multidictproxy import MultiDictProxy
from werkzeug.datastructures import FileStorage

from rotkehlchen.accounting.structures import ActionType, LedgerAction, LedgerActionType
from rotkehlchen.api.rest import RestAPI
from rotkehlchen.api.v1.encoding import (
    AllBalancesQuerySchema,
    AssetIconsSchema,
    AssetIconUploadSchema,
    AsyncHistoricalQuerySchema,
    AsyncQueryArgumentSchema,
    AsyncTasksQuerySchema,
    BaseXpubSchema,
    BlockchainAccountsDeleteSchema,
    BlockchainAccountsGetSchema,
    BlockchainAccountsPatchSchema,
    BlockchainAccountsPutSchema,
    BlockchainBalanceQuerySchema,
    CurrentAssetsPriceSchema,
    DataImportSchema,
    EditSettingsSchema,
    EthereumTransactionQuerySchema,
    ExchangeBalanceQuerySchema,
    ExchangeRatesSchema,
    ExchangesDataResourceSchema,
    ExchangesResourceAddSchema,
    ExchangesResourceRemoveSchema,
    ExternalServicesResourceAddSchema,
    ExternalServicesResourceDeleteSchema,
    HistoricalAssetsPriceSchema,
    HistoryExportingSchema,
    HistoryProcessingSchema,
    IgnoredActionsGetSchema,
    IgnoredActionsModifySchema,
    IgnoredAssetsSchema,
    LedgerActionEditSchema,
    LedgerActionIdentifierSchema,
    LedgerActionSchema,
    ManuallyTrackedBalancesDeleteSchema,
    ManuallyTrackedBalancesSchema,
    ModifyEthereumTokenSchema,
    NamedEthereumModuleDataSchema,
    NamedOracleCacheCreateSchema,
    NamedOracleCacheGetSchema,
    NamedOracleCacheSchema,
    NewUserSchema,
    OptionalEthereumAddressSchema,
    QueriedAddressesSchema,
    RequiredEthereumAddressSchema,
    StatisticsAssetBalanceSchema,
    StatisticsValueDistributionSchema,
    TagDeleteSchema,
    TagEditSchema,
    TagSchema,
    TimerangeLocationCacheQuerySchema,
    TimerangeLocationQuerySchema,
    TradeDeleteSchema,
    TradePatchSchema,
    TradeSchema,
    UserActionSchema,
    UserPasswordChangeSchema,
    # UserPremiumSyncSchema removed
    WatchersAddSchema,
    WatchersDeleteSchema,
    WatchersEditSchema,
    XpubAddSchema,
    XpubPatchSchema,
)
from rotkehlchen.api.v1.parser import resource_parser
from rotkehlchen.assets.asset import Asset
from rotkehlchen.balances.manual import ManuallyTrackedBalance
from rotkehlchen.chain.bitcoin.xpub import XpubData
from rotkehlchen.db.settings import ModifiableDBSettings
from rotkehlchen.history.typing import HistoricalPriceOracle
from rotkehlchen.typing import (
    ApiKey,
    ApiSecret,
    AssetAmount,
    BlockchainAccountData,
    ChecksumEthAddress,
    ExternalService,
    ExternalServiceApiCredentials,
    Fee,
    HexColorCode,
    ListOfBlockchainAddresses,
    Location,
    ModuleName,
    Price,
    SupportedBlockchain,
    Timestamp,
    TradePair,
    TradeType,
)

if TYPE_CHECKING:
    from rotkehlchen.chain.bitcoin.hdkey import HDKey
    from rotkehlchen.chain.ethereum.typing import CustomEthereumToken


def _combine_parser_data(
        data_1: Dict[str, Any],
        data_2: Dict[str, Any],
        schema: Schema,
) -> MultiDictProxy:
    if data_2 is not missing:
        if data_1 == {}:
            data_1 = MultiDictProxy(data_2, schema)
        else:
            all_data = data_1.to_dict() if isinstance(data_1, MultiDictProxy) else data_1
            for key, value in data_2.items():
                all_data[key] = value
            data_1 = MultiDictProxy(all_data, schema)
    return data_1


@parser.location_loader('json_and_view_args')  # type: ignore
def load_json_viewargs_data(request: Request, schema: Schema) -> Dict[str, Any]:
    """Load data from a request accepting either json or view_args encoded data"""
    view_args = parser.load_view_args(request, schema)
    data = parser.load_json(request, schema)
    if data is missing:
        return data

    data = _combine_parser_data(data, view_args, schema)
    return data


@parser.location_loader('json_and_query')  # type: ignore
def load_json_query_data(request: Request, schema: Schema) -> Dict[str, Any]:
    """Load data from a request accepting either json or query encoded data"""
    data = parser.load_json(request, schema)
    if data is not missing:
        return data
    return parser.load_querystring(request, schema)


@parser.location_loader('json_and_query_and_view_args')  # type: ignore
def load_json_query_viewargs_data(request: Request, schema: Schema) -> Dict[str, Any]:
    """Load data from a request accepting either json or querystring or view_args encoded data"""
    view_args = parser.load_view_args(request, schema)
    # Get data either from json or from querystring
    data = parser.load_json(request, schema)
    if data is missing:
        data = parser.load_querystring(request, schema)

    if data is missing:
        return data

    data = _combine_parser_data(data, view_args, schema)
    return data


@parser.location_loader('form_and_file')  # type: ignore
def load_form_file_data(request: Request, schema: Schema) -> Dict[str, Any]:
    """Load data from a request accepting form and file encoded data"""
    form_data = parser.load_form(request, schema)
    file_data = parser.load_files(request, schema)
    data = _combine_parser_data(form_data, file_data, schema)
    return data


@parser.location_loader('view_args_and_file')  # type: ignore
def load_view_args_file_data(request: Request, schema: Schema) -> Dict[str, Any]:
    """Load data from a request accepting view_args and file encoded data"""
    view_args_data = parser.load_view_args(request, schema)
    file_data = parser.load_files(request, schema)
    data = _combine_parser_data(view_args_data, file_data, schema)
    return data


def create_blueprint() -> Blueprint:
    # Take a look at this SO question on hints how to organize versioned
    # API with flask:
    # http://stackoverflow.com/questions/28795561/support-multiple-api-versions-in-flask#28797512
    return Blueprint("v1_resources", __name__)


class BaseResource(Resource):
    def __init__(self, rest_api_object: RestAPI, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.rest_api = rest_api_object


class SettingsResource(BaseResource):

    put_schema = EditSettingsSchema()

    @use_kwargs(put_schema, location='json')  # type: ignore
    def put(
            self,
            settings: ModifiableDBSettings,
    ) -> Response:
        return self.rest_api.set_settings(settings)

    def get(self) -> Response:
        return self.rest_api.get_settings()


class AsyncTasksResource(BaseResource):

    get_schema = AsyncTasksQuerySchema()

    @use_kwargs(get_schema, location='view_args')  # type: ignore
    def get(self, task_id: Optional[int]) -> Response:
        return self.rest_api.query_tasks_outcome(task_id=task_id)


class ExchangeRatesResource(BaseResource):

    get_schema = ExchangeRatesSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(self, currencies: List[Asset]) -> Response:
        return self.rest_api.get_exchange_rates(given_currencies=currencies)


class ExchangesResource(BaseResource):

    put_schema = ExchangesResourceAddSchema()
    delete_schema = ExchangesResourceRemoveSchema()

    def get(self) -> Response:
        return self.rest_api.get_exchanges()

    @use_kwargs(put_schema, location='json')  # type: ignore
    def put(
            self,
            name: str,
            api_key: ApiKey,
            api_secret: ApiSecret,
            passphrase: Optional[str],
    ) -> Response:
        return self.rest_api.setup_exchange(name, api_key, api_secret, passphrase)

    @use_kwargs(delete_schema, location='json')  # type: ignore
    def delete(self, name: str) -> Response:
        return self.rest_api.remove_exchange(name=name)


class ExchangesDataResource(BaseResource):

    delete_schema = ExchangesDataResourceSchema()

    @use_kwargs(delete_schema, location='view_args')  # type: ignore
    def delete(self, name: Optional[str]) -> Response:
        return self.rest_api.purge_exchange_data(name=name)


class EthereumTransactionsResource(BaseResource):
    get_schema = EthereumTransactionQuerySchema()

    @use_kwargs(get_schema, location='json_and_query_and_view_args')  # type: ignore
    def get(
            self,
            async_query: bool,
            address: Optional[ChecksumEthAddress],
            from_timestamp: Timestamp,
            to_timestamp: Timestamp,
            only_cache: bool,
    ) -> Response:
        return self.rest_api.get_ethereum_transactions(
            async_query=async_query,
            address=address,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
            only_cache=only_cache,
        )

    def delete(self) -> Response:
        return self.rest_api.purge_ethereum_transaction_data()


class EthereumAirdropsResource(BaseResource):

    get_schema = AsyncQueryArgumentSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(self, async_query: bool) -> Response:
        return self.rest_api.get_ethereum_airdrops(async_query)


class ExternalServicesResource(BaseResource):

    put_schema = ExternalServicesResourceAddSchema()
    delete_schema = ExternalServicesResourceDeleteSchema()

    def get(self) -> Response:
        return self.rest_api.get_external_services()

    @use_kwargs(put_schema, location='json')  # type: ignore
    def put(
            self,
            services: List[ExternalServiceApiCredentials],
    ) -> Response:
        return self.rest_api.add_external_services(services=services)

    @use_kwargs(delete_schema, location='json')  # type: ignore
    def delete(self, services: List[ExternalService]) -> Response:
        return self.rest_api.delete_external_services(services=services)


class AllBalancesResource(BaseResource):

    get_schema = AllBalancesQuerySchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(self, save_data: bool, async_query: bool, ignore_cache: bool) -> Response:
        return self.rest_api.query_all_balances(
            save_data=save_data,
            async_query=async_query,
            ignore_cache=ignore_cache,
        )


class ExchangeBalancesResource(BaseResource):

    get_schema = ExchangeBalanceQuerySchema()

    @use_kwargs(get_schema, location='json_and_query_and_view_args')  # type: ignore
    def get(self, name: Optional[str], async_query: bool, ignore_cache: bool) -> Response:
        return self.rest_api.query_exchange_balances(
            name=name,
            async_query=async_query,
            ignore_cache=ignore_cache,
        )


class OwnedAssetsResource(BaseResource):

    def get(self) -> Response:
        return self.rest_api.query_owned_assets()


class AllAssetsResource(BaseResource):

    def get(self) -> Response:
        return self.rest_api.query_all_assets()


class EthereumAssetsResource(BaseResource):

    get_schema = OptionalEthereumAddressSchema()
    delete_schema = RequiredEthereumAddressSchema()
    edit_schema = ModifyEthereumTokenSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(self, address: Optional[ChecksumEthAddress]) -> Response:
        return self.rest_api.get_custom_ethereum_tokens(address=address)

    @use_kwargs(edit_schema, location='json')  # type: ignore
    def put(self, token: 'CustomEthereumToken') -> Response:
        return self.rest_api.add_custom_ethereum_token(token=token)

    @use_kwargs(edit_schema, location='json')  # type: ignore
    def patch(self, token: 'CustomEthereumToken') -> Response:
        return self.rest_api.edit_custom_ethereum_token(token=token)

    @use_kwargs(delete_schema, location='json')  # type: ignore
    def delete(self, address: ChecksumEthAddress) -> Response:
        return self.rest_api.delete_custom_ethereum_token(address)


class BlockchainBalancesResource(BaseResource):

    get_schema = BlockchainBalanceQuerySchema()

    @use_kwargs(get_schema, location='json_and_query_and_view_args')  # type: ignore
    def get(
            self,
            blockchain: Optional[SupportedBlockchain],
            async_query: bool,
            ignore_cache: bool,
    ) -> Response:
        return self.rest_api.query_blockchain_balances(
            blockchain=blockchain,
            async_query=async_query,
            ignore_cache=ignore_cache,
        )


class ManuallyTrackedBalancesResource(BaseResource):

    get_schema = AsyncQueryArgumentSchema()
    edit_schema = ManuallyTrackedBalancesSchema()
    delete_schema = ManuallyTrackedBalancesDeleteSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(self, async_query: bool) -> Response:
        return self.rest_api.get_manually_tracked_balances(async_query)

    @use_kwargs(edit_schema, location='json')  # type: ignore
    def put(self, async_query: bool, balances: List[ManuallyTrackedBalance]) -> Response:
        return self.rest_api.add_manually_tracked_balances(async_query=async_query, data=balances)

    @use_kwargs(edit_schema, location='json')  # type: ignore
    def patch(self, async_query: bool, balances: List[ManuallyTrackedBalance]) -> Response:
        return self.rest_api.edit_manually_tracked_balances(async_query=async_query, data=balances)

    @use_kwargs(delete_schema, location='json')  # type: ignore
    def delete(self, async_query: bool, labels: List[str]) -> Response:
        return self.rest_api.remove_manually_tracked_balances(
            async_query=async_query,
            labels=labels,
        )


class TradesResource(BaseResource):

    get_schema = TimerangeLocationCacheQuerySchema()
    put_schema = TradeSchema()
    patch_schema = TradePatchSchema()
    delete_schema = TradeDeleteSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(
            self,
            from_timestamp: Timestamp,
            to_timestamp: Timestamp,
            location: Optional[Location],
            async_query: bool,
            only_cache: bool,
    ) -> Response:
        return self.rest_api.get_trades(
            from_ts=from_timestamp,
            to_ts=to_timestamp,
            location=location,
            async_query=async_query,
            only_cache=only_cache,
        )

    @use_kwargs(put_schema, location='json')  # type: ignore
    def put(
            self,
            timestamp: Timestamp,
            location: Location,
            pair: TradePair,
            trade_type: TradeType,
            amount: AssetAmount,
            rate: Price,
            fee: Fee,
            fee_currency: Asset,
            link: str,
            notes: str,
    ) -> Response:
        return self.rest_api.add_trade(
            timestamp=timestamp,
            location=location,
            pair=pair,
            trade_type=trade_type,
            amount=amount,
            rate=rate,
            fee=fee,
            fee_currency=fee_currency,
            link=link,
            notes=notes,
        )

    @use_kwargs(patch_schema, location='json')  # type: ignore
    def patch(
            self,
            trade_id: str,
            timestamp: Timestamp,
            location: Location,
            pair: TradePair,
            trade_type: TradeType,
            amount: AssetAmount,
            rate: Price,
            fee: Fee,
            fee_currency: Asset,
            link: str,
            notes: str,
    ) -> Response:
        return self.rest_api.edit_trade(
            trade_id=trade_id,
            timestamp=timestamp,
            location=location,
            pair=pair,
            trade_type=trade_type,
            amount=amount,
            rate=rate,
            fee=fee,
            fee_currency=fee_currency,
            link=link,
            notes=notes,
        )

    @use_kwargs(delete_schema, location='json')  # type: ignore
    def delete(self, trade_id: str) -> Response:
        return self.rest_api.delete_trade(trade_id=trade_id)


class AssetMovementsResource(BaseResource):

    get_schema = TimerangeLocationCacheQuerySchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(
            self,
            from_timestamp: Timestamp,
            to_timestamp: Timestamp,
            location: Optional[Location],
            async_query: bool,
            only_cache: bool,
    ) -> Response:
        return self.rest_api.get_asset_movements(
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
            location=location,
            async_query=async_query,
            only_cache=only_cache,
        )


class TagsResource(BaseResource):

    put_schema = TagSchema()
    patch_schema = TagEditSchema()
    delete_schema = TagDeleteSchema()

    def get(self) -> Response:
        return self.rest_api.get_tags()

    @use_kwargs(put_schema, location='json')  # type: ignore
    def put(
            self,
            name: str,
            description: Optional[str],
            background_color: HexColorCode,
            foreground_color: HexColorCode,
    ) -> Response:
        return self.rest_api.add_tag(
            name=name,
            description=description,
            background_color=background_color,
            foreground_color=foreground_color,
        )

    @use_kwargs(patch_schema, location='json')  # type: ignore
    def patch(
            self,
            name: str,
            description: Optional[str],
            background_color: Optional[HexColorCode],
            foreground_color: Optional[HexColorCode],
    ) -> Response:
        return self.rest_api.edit_tag(
            name=name,
            description=description,
            background_color=background_color,
            foreground_color=foreground_color,
        )

    @use_kwargs(delete_schema, location='json')  # type: ignore
    def delete(self, name: str) -> Response:
        return self.rest_api.delete_tag(name=name)


class LedgerActionsResource(BaseResource):

    get_schema = TimerangeLocationQuerySchema()
    put_schema = LedgerActionSchema()
    patch_schema = LedgerActionEditSchema()
    delete_schema = LedgerActionIdentifierSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(
            self,
            from_timestamp: Timestamp,
            to_timestamp: Timestamp,
            location: Optional[Location],
            async_query: bool,
    ) -> Response:
        return self.rest_api.get_ledger_actions(
            from_ts=from_timestamp,
            to_ts=to_timestamp,
            location=location,
            async_query=async_query,
        )

    @use_kwargs(put_schema, location='json')  # type: ignore
    def put(
            self,
            timestamp: Timestamp,
            action_type: LedgerActionType,
            location: Location,
            amount: AssetAmount,
            asset: Asset,
            link: str,
            notes: str,
    ) -> Response:
        return self.rest_api.add_ledger_action(
            timestamp=timestamp,
            action_type=action_type,
            location=location,
            amount=amount,
            asset=asset,
            link=link,
            notes=notes,
        )

    @use_kwargs(patch_schema, location='json')  # type: ignore
    def patch(self, action: LedgerAction) -> Response:
        return self.rest_api.edit_ledger_action(action=action)

    @use_kwargs(delete_schema, location='json')  # type: ignore
    def delete(self, identifier: int) -> Response:
        return self.rest_api.delete_ledger_action(identifier=identifier)


class UsersResource(BaseResource):

    put_schema = NewUserSchema()

    def get(self) -> Response:
        return self.rest_api.get_users()

    @use_kwargs(put_schema, location='json')  # type: ignore
    def put(
            self,
            name: str,
            password: str,
            # premium parameters removed
            initial_settings: Optional[ModifiableDBSettings],
    ) -> Response:
        return self.rest_api.create_new_user(
            name=name,
            password=password,
            # premium parameters removed
            initial_settings=initial_settings,
        )


class UsersByNameResource(BaseResource):
    patch_schema = UserActionSchema()

    @use_kwargs(patch_schema, location='json_and_view_args')  # type: ignore
    def patch(
            self,
            action: Optional[str],
            name: str,
            password: Optional[str],
            sync_approval: Literal['yes', 'no', 'unknown'],
            # premium parameters removed
    ) -> Response:
        # Premium credential setting removed - only login/logout supported
        if action == 'login':
            assert password is not None, 'Marshmallow validation should not let password=None here'
            return self.rest_api.user_login(
                name=name,
                password=password,
                sync_approval=sync_approval,
            )

        # else can only be logout -- checked by marshmallow
        return self.rest_api.user_logout(name=name)


class UserPasswordChangeResource(BaseResource):
    patch_schema = UserPasswordChangeSchema

    @use_kwargs(patch_schema, location='json')  # type: ignore
    def patch(
            self,
            name: str,
            current_password: str,
            new_password: str,
    ) -> Response:
        return self.rest_api.user_change_password(
            name=name,
            current_password=current_password,
            new_password=new_password,
        )


# Premium resource classes removed


class StatisticsNetvalueResource(BaseResource):

    def get(self) -> Response:
        return self.rest_api.query_netvalue_data()


class StatisticsAssetBalanceResource(BaseResource):

    get_schema = StatisticsAssetBalanceSchema()

    @use_kwargs(get_schema, location='json_and_query_and_view_args')  # type: ignore
    def get(
            self,
            asset: Asset,
            from_timestamp: Timestamp,
            to_timestamp: Timestamp,
    ) -> Response:
        return self.rest_api.query_timed_balances_data(
            asset=asset,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )


class StatisticsValueDistributionResource(BaseResource):

    get_schema = StatisticsValueDistributionSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(self, distribution_by: str) -> Response:
        return self.rest_api.query_value_distribution_data(
            distribution_by=distribution_by,
        )


class StatisticsRendererResource(BaseResource):

    def get(self) -> Response:
        return self.rest_api.query_statistics_renderer()


class MessagesResource(BaseResource):

    def get(self) -> Response:
        return self.rest_api.get_messages()


class HistoryStatusResource(BaseResource):

    def get(self) -> Response:
        return self.rest_api.get_history_status()


class HistoryProcessingResource(BaseResource):

    get_schema = HistoryProcessingSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(
            self,
            from_timestamp: Timestamp,
            to_timestamp: Timestamp,
            async_query: bool,
    ) -> Response:
        return self.rest_api.process_history(
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
            async_query=async_query,
        )


class HistoryExportingResource(BaseResource):

    get_schema = HistoryExportingSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(self, directory_path: Path) -> Response:
        return self.rest_api.export_processed_history_csv(directory_path=directory_path)


class HistoryDownloadingResource(BaseResource):

    def get(self) -> Response:
        return self.rest_api.download_processed_history_csv()


class PeriodicDataResource(BaseResource):

    def get(self) -> Response:
        return self.rest_api.query_periodic_data()


class BlockchainsAccountsResource(BaseResource):

    get_schema = BlockchainAccountsGetSchema()

    def make_put_schema(self) -> BlockchainAccountsPutSchema:
        return BlockchainAccountsPutSchema(
            self.rest_api.rotkehlchen.chain_manager.ethereum,
        )

    def make_patch_schema(self) -> BlockchainAccountsPatchSchema:
        return BlockchainAccountsPatchSchema(
            self.rest_api.rotkehlchen.chain_manager.ethereum,
        )

    def make_delete_schema(self) -> BlockchainAccountsDeleteSchema:
        return BlockchainAccountsDeleteSchema(
            self.rest_api.rotkehlchen.chain_manager.ethereum,
        )

    @use_kwargs(get_schema, location='view_args')  # type: ignore
    def get(self, blockchain: SupportedBlockchain) -> Response:
        return self.rest_api.get_blockchain_accounts(blockchain)

    @resource_parser.use_kwargs(make_put_schema, location='json_and_view_args')  # type: ignore
    def put(
            self,
            blockchain: SupportedBlockchain,
            accounts: List[Dict[str, Any]],
            async_query: bool,
    ) -> Response:
        account_data = [
            BlockchainAccountData(
                address=entry['address'],
                label=entry['label'],
                tags=entry['tags'],
            ) for entry in accounts
        ]
        return self.rest_api.add_blockchain_accounts(
            blockchain=blockchain,
            account_data=account_data,
            async_query=async_query,
        )

    @resource_parser.use_kwargs(make_patch_schema, location='json_and_view_args')  # type: ignore
    def patch(
            self,
            blockchain: SupportedBlockchain,
            accounts: List[Dict[str, Any]],
    ) -> Response:
        account_data = [
            BlockchainAccountData(
                address=entry['address'],
                label=entry['label'],
                tags=entry['tags'],
            ) for entry in accounts
        ]
        return self.rest_api.edit_blockchain_accounts(
            blockchain=blockchain,
            account_data=account_data,
        )

    @resource_parser.use_kwargs(make_delete_schema, location='json_and_view_args')  # type: ignore
    def delete(
            self,
            blockchain: SupportedBlockchain,
            accounts: ListOfBlockchainAddresses,
            async_query: bool,
    ) -> Response:
        return self.rest_api.remove_blockchain_accounts(
            blockchain=blockchain,
            accounts=accounts,
            async_query=async_query,
        )


class BTCXpubResource(BaseResource):

    put_schema = XpubAddSchema()
    delete_schema = BaseXpubSchema()
    patch_schema = XpubPatchSchema()

    @use_kwargs(put_schema, location='json')  # type: ignore
    def put(
            self,
            xpub: 'HDKey',
            derivation_path: Optional[str],
            label: Optional[str],
            tags: Optional[List[str]],
            async_query: bool,
    ) -> Response:
        return self.rest_api.add_xpub(
            xpub_data=XpubData(
                xpub=xpub,
                derivation_path=derivation_path,
                label=label,
                tags=tags,
            ),
            async_query=async_query,
        )

    @use_kwargs(delete_schema, location='json')  # type: ignore
    def delete(
            self,
            xpub: 'HDKey',
            derivation_path: Optional[str],
            async_query: bool,
    ) -> Response:
        return self.rest_api.delete_xpub(
            xpub_data=XpubData(
                xpub=xpub,
                derivation_path=derivation_path,
                label=None,
                tags=None,
            ),
            async_query=async_query,
        )

    @use_kwargs(patch_schema, location='json_and_view_args')  # type: ignore
    def patch(
            self,
            xpub: 'HDKey',
            derivation_path: Optional[str],
            label: Optional[str],
            tags: Optional[List[str]],
    ) -> Response:
        return self.rest_api.edit_xpub(
            xpub_data=XpubData(
                xpub=xpub,
                derivation_path=derivation_path,
                label=label,
                tags=tags,
            ),
        )


class IgnoredAssetsResource(BaseResource):

    modify_schema = IgnoredAssetsSchema()

    def get(self) -> Response:
        return self.rest_api.get_ignored_assets()

    @use_kwargs(modify_schema, location='json')  # type: ignore
    def put(self, assets: List[Asset]) -> Response:
        return self.rest_api.add_ignored_assets(assets=assets)

    @use_kwargs(modify_schema, location='json')  # type: ignore
    def delete(self, assets: List[Asset]) -> Response:
        return self.rest_api.remove_ignored_assets(assets=assets)


class IgnoredActionsResource(BaseResource):

    get_schema = IgnoredActionsGetSchema()
    modify_schema = IgnoredActionsModifySchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(self, action_type: Optional[ActionType]) -> Response:
        return self.rest_api.get_ignored_action_ids(action_type=action_type)

    @use_kwargs(modify_schema, location='json')  # type: ignore
    def put(self, action_type: ActionType, action_ids: List[str]) -> Response:
        return self.rest_api.add_ignored_action_ids(action_type=action_type, action_ids=action_ids)

    @use_kwargs(modify_schema, location='json')  # type: ignore
    def delete(self, action_type: ActionType, action_ids: List[str]) -> Response:
        return self.rest_api.remove_ignored_action_ids(
            action_type=action_type,
            action_ids=action_ids,
        )


class QueriedAddressesResource(BaseResource):

    modify_schema = QueriedAddressesSchema()

    def get(self) -> Response:
        return self.rest_api.get_queried_addresses_per_module()

    @use_kwargs(modify_schema, location='json')  # type: ignore
    def put(self, module: ModuleName, address: ChecksumEthAddress) -> Response:
        return self.rest_api.add_queried_address_per_module(module=module, address=address)

    @use_kwargs(modify_schema, location='json')  # type: ignore
    def delete(self, module: ModuleName, address: ChecksumEthAddress) -> Response:
        return self.rest_api.remove_queried_address_per_module(module=module, address=address)


class VersionResource(BaseResource):

    def get(self) -> Response:
        return self.rest_api.version_check()


class PingResource(BaseResource):

    def get(self) -> Response:
        return self.rest_api.ping()


class DataImportResource(BaseResource):

    upload_schema = DataImportSchema()

    @use_kwargs(upload_schema, location='json')  # type: ignore
    def put(self, source: Literal['cointracking.info', 'crypto.com'], file: Path) -> Response:
        return self.rest_api.import_data(source=source, filepath=file)

    @use_kwargs(upload_schema, location='form_and_file')  # type: ignore
    def post(
            self,
            source: Literal['cointracking.info', 'crypto.com'],
            file: FileStorage,
    ) -> Response:
        with TemporaryDirectory() as temp_directory:
            filename = file.filename if file.filename else f'{source}.csv'
            filepath = Path(temp_directory) / filename
            file.save(str(filepath))
            response = self.rest_api.import_data(source=source, filepath=filepath)

        return response


class Eth2StakeDepositsResource(BaseResource):

    get_schema = AsyncQueryArgumentSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(self, async_query: bool) -> Response:
        return self.rest_api.get_eth2_stake_deposits(async_query)


class Eth2StakeDetailsResource(BaseResource):

    get_schema = AsyncQueryArgumentSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(self, async_query: bool) -> Response:
        return self.rest_api.get_eth2_stake_details(async_query)


class DefiBalancesResource(BaseResource):

    get_schema = AsyncQueryArgumentSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(self, async_query: bool) -> Response:
        return self.rest_api.get_defi_balances(async_query)


class NamedEthereumModuleDataResource(BaseResource):
    delete_schema = NamedEthereumModuleDataSchema()

    @use_kwargs(delete_schema, location='view_args')  # type: ignore
    def delete(self, module_name: ModuleName) -> Response:
        return self.rest_api.purge_module_data(module_name)


class EthereumModuleDataResource(BaseResource):

    def delete(self) -> Response:
        return self.rest_api.purge_module_data(module_name=None)


class EthereumModuleResource(BaseResource):

    def get(self) -> Response:
        return self.rest_api.supported_modules()


class MakerdaoDSRBalanceResource(BaseResource):

    get_schema = AsyncQueryArgumentSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(self, async_query: bool) -> Response:
        return self.rest_api.get_makerdao_dsr_balance(async_query)


class MakerdaoDSRHistoryResource(BaseResource):

    get_schema = AsyncQueryArgumentSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(self, async_query: bool) -> Response:
        return self.rest_api.get_makerdao_dsr_history(async_query)


class MakerdaoVaultsResource(BaseResource):

    get_schema = AsyncQueryArgumentSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(self, async_query: bool) -> Response:
        return self.rest_api.get_makerdao_vaults(async_query)


class MakerdaoVaultDetailsResource(BaseResource):

    get_schema = AsyncQueryArgumentSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(self, async_query: bool) -> Response:
        return self.rest_api.get_makerdao_vault_details(async_query)


class AaveBalancesResource(BaseResource):

    get_schema = AsyncQueryArgumentSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(self, async_query: bool) -> Response:
        return self.rest_api.get_aave_balances(async_query)


class AaveHistoryResource(BaseResource):

    get_schema = AsyncHistoricalQuerySchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(
            self,
            async_query: bool,
            reset_db_data: bool,
            from_timestamp: Timestamp,
            to_timestamp: Timestamp,
    ) -> Response:
        return self.rest_api.get_aave_history(
            async_query=async_query,
            reset_db_data=reset_db_data,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )


class AdexBalancesResource(BaseResource):

    get_schema = AsyncQueryArgumentSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(self, async_query: bool) -> Response:
        return self.rest_api.get_adex_balances(async_query=async_query)


class AdexHistoryResource(BaseResource):

    get_schema = AsyncHistoricalQuerySchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(
            self,
            async_query: bool,
            reset_db_data: bool,
            from_timestamp: Timestamp,
            to_timestamp: Timestamp,
    ) -> Response:
        return self.rest_api.get_adex_history(
            async_query=async_query,
            reset_db_data=reset_db_data,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )


class CompoundBalancesResource(BaseResource):

    get_schema = AsyncQueryArgumentSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(self, async_query: bool) -> Response:
        return self.rest_api.get_compound_balances(async_query)


class CompoundHistoryResource(BaseResource):

    get_schema = AsyncHistoricalQuerySchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(
            self,
            async_query: bool,
            reset_db_data: bool,
            from_timestamp: Timestamp,
            to_timestamp: Timestamp,
    ) -> Response:
        return self.rest_api.get_compound_history(
            async_query=async_query,
            reset_db_data=reset_db_data,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )


class YearnVaultsBalancesResource(BaseResource):

    get_schema = AsyncQueryArgumentSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(self, async_query: bool) -> Response:
        return self.rest_api.get_yearn_vaults_balances(async_query)


class YearnVaultsHistoryResource(BaseResource):

    get_schema = AsyncHistoricalQuerySchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(
            self,
            async_query: bool,
            reset_db_data: bool,
            from_timestamp: Timestamp,
            to_timestamp: Timestamp,
    ) -> Response:
        return self.rest_api.get_yearn_vaults_history(
            async_query=async_query,
            reset_db_data=reset_db_data,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )


class UniswapBalancesResource(BaseResource):

    get_schema = AsyncQueryArgumentSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(self, async_query: bool) -> Response:
        return self.rest_api.get_uniswap_balances(async_query=async_query)


class UniswapEventsHistoryResource(BaseResource):

    get_schema = AsyncHistoricalQuerySchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(
            self,
            async_query: bool,
            reset_db_data: bool,
            from_timestamp: Timestamp,
            to_timestamp: Timestamp,
    ) -> Response:
        return self.rest_api.get_uniswap_events_history(
            async_query=async_query,
            reset_db_data=reset_db_data,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )


class UniswapTradesHistoryResource(BaseResource):

    get_schema = AsyncHistoricalQuerySchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(
            self,
            async_query: bool,
            reset_db_data: bool,
            from_timestamp: Timestamp,
            to_timestamp: Timestamp,
    ) -> Response:
        return self.rest_api.get_uniswap_trades_history(
            async_query=async_query,
            reset_db_data=reset_db_data,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )


class LoopringBalancesResource(BaseResource):

    get_schema = AsyncQueryArgumentSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(self, async_query: bool) -> Response:
        return self.rest_api.get_loopring_balances(async_query=async_query)


class BalancerBalancesResource(BaseResource):

    get_schema = AsyncQueryArgumentSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(self, async_query: bool) -> Response:
        return self.rest_api.get_balancer_balances(async_query=async_query)


class BalancerEventsHistoryResource(BaseResource):

    get_schema = AsyncHistoricalQuerySchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(
            self,
            async_query: bool,
            reset_db_data: bool,
            from_timestamp: Timestamp,
            to_timestamp: Timestamp,
    ) -> Response:
        return self.rest_api.get_balancer_events_history(
            async_query=async_query,
            reset_db_data=reset_db_data,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )


class BalancerTradesHistoryResource(BaseResource):

    get_schema = AsyncHistoricalQuerySchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(
            self,
            async_query: bool,
            reset_db_data: bool,
            from_timestamp: Timestamp,
            to_timestamp: Timestamp,
    ) -> Response:
        return self.rest_api.get_balancer_trades_history(
            async_query=async_query,
            reset_db_data=reset_db_data,
            from_timestamp=from_timestamp,
            to_timestamp=to_timestamp,
        )


class WatchersResource(BaseResource):

    put_schema = WatchersAddSchema
    patch_schema = WatchersEditSchema
    delete_schema = WatchersDeleteSchema

    def get(self) -> Response:
        return self.rest_api.get_watchers()

    @use_kwargs(put_schema, location='json')  # type: ignore
    def put(self, watchers: List[Dict[str, Any]]) -> Response:
        return self.rest_api.add_watchers(watchers)

    @use_kwargs(patch_schema, location='json')  # type: ignore
    def patch(self, watchers: List[Dict[str, Any]]) -> Response:
        return self.rest_api.edit_watchers(watchers)

    @use_kwargs(delete_schema, location='json')  # type: ignore
    def delete(self, watchers: List[str]) -> Response:
        return self.rest_api.delete_watchers(watchers)


class AssetIconsResource(BaseResource):

    get_schema = AssetIconsSchema()
    upload_schema = AssetIconUploadSchema()

    @use_kwargs(get_schema, location='view_args')  # type: ignore
    def get(self, asset: Asset, size: Literal['thumb', 'small', 'large']) -> Response:
        # Process the if-match and if-none-match headers so that comparison with etag can be done
        match_header = flask_request.headers.get('If-Match', None)
        if not match_header:
            match_header = flask_request.headers.get('If-None-Match', None)
        if match_header:
            match_header = match_header[1:-1]  # remove enclosing quotes

        return self.rest_api.get_asset_icon(asset, size, match_header)

    @use_kwargs(upload_schema, location='json_and_view_args')  # type: ignore
    def put(self, asset: Asset, file: Path) -> Response:
        return self.rest_api.upload_asset_icon(asset=asset, filepath=file)

    @use_kwargs(upload_schema, location='view_args_and_file')  # type: ignore
    def post(self, asset: Asset, file: FileStorage) -> Response:
        with TemporaryDirectory() as temp_directory:
            filename = file.filename if file.filename else f'{asset.identifier}.png'
            filepath = Path(temp_directory) / filename
            file.save(str(filepath))
            response = self.rest_api.upload_asset_icon(asset=asset, filepath=filepath)

        return response


class CurrentAssetsPriceResource(BaseResource):

    get_schema = CurrentAssetsPriceSchema()

    @use_kwargs(get_schema, location='json_and_query')  # type: ignore
    def get(
            self,
            assets: List[Asset],
            target_asset: Asset,
            ignore_cache: bool,
            async_query: bool,
    ) -> Response:
        return self.rest_api.get_current_assets_price(
            assets=assets,
            target_asset=target_asset,
            ignore_cache=ignore_cache,
            async_query=async_query,
        )


class HistoricalAssetsPriceResource(BaseResource):

    post_schema = HistoricalAssetsPriceSchema()

    @use_kwargs(post_schema, location='json')  # type: ignore
    def post(
            self,
            assets_timestamp: List[Tuple[Asset, Timestamp]],
            target_asset: Asset,
            async_query: bool,
    ) -> Response:
        return self.rest_api.get_historical_assets_price(
            assets_timestamp=assets_timestamp,
            target_asset=target_asset,
            async_query=async_query,
        )


class NamedOracleCacheResource(BaseResource):

    post_schema = NamedOracleCacheCreateSchema()
    delete_schema = NamedOracleCacheSchema()
    get_schema = NamedOracleCacheGetSchema()

    @use_kwargs(get_schema, location='json_and_query_and_view_args')  # type: ignore
    def get(self, oracle: HistoricalPriceOracle, async_query: bool) -> Response:
        return self.rest_api.get_oracle_cache(oracle=oracle, async_query=async_query)

    @use_kwargs(post_schema, location='json_and_view_args')  # type: ignore
    def post(
            self,
            oracle: HistoricalPriceOracle,
            from_asset: Asset,
            to_asset: Asset,
            purge_old: bool,
            async_query: bool,
    ) -> Response:
        return self.rest_api.create_oracle_cache(
            oracle=oracle,
            from_asset=from_asset,
            to_asset=to_asset,
            purge_old=purge_old,
            async_query=async_query,
        )

    @use_kwargs(delete_schema, location='json_and_view_args')  # type: ignore
    def delete(
            self,
            oracle: HistoricalPriceOracle,
            from_asset: Asset,
            to_asset: Asset,
    ) -> Response:
        return self.rest_api.delete_oracle_cache(
            oracle=oracle,
            from_asset=from_asset,
            to_asset=to_asset,
        )


class OraclesResource(BaseResource):

    def get(self) -> Response:
        return self.rest_api.get_supported_oracles()
