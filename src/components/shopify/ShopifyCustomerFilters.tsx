type LifecycleFilter = "all" | "new" | "recurring";
type SortBy = "total_spent" | "total_orders" | "last_purchase_at";

type Props = {
  search: string;
  onSearchChange: (value: string) => void;
  minTotalSpent: string;
  maxTotalSpent: string;
  onMinTotalSpentChange: (value: string) => void;
  onMaxTotalSpentChange: (value: string) => void;
  minOrders: string;
  onMinOrdersChange: (value: string) => void;
  lifecycle: LifecycleFilter;
  onLifecycleChange: (value: LifecycleFilter) => void;
  sortBy: SortBy;
  onSortByChange: (value: SortBy) => void;
};

export default function ShopifyCustomerFilters({
  search,
  onSearchChange,
  minTotalSpent,
  maxTotalSpent,
  onMinTotalSpentChange,
  onMaxTotalSpentChange,
  minOrders,
  onMinOrdersChange,
  lifecycle,
  onLifecycleChange,
  sortBy,
  onSortByChange,
}: Props) {
  return (
    <div className="shopifyCustomerFilters">
      <label className="shopifyFilterField">
        <span>Buscar</span>
        <input
          className="shopifyTextInput"
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="Nome ou e-mail"
          type="search"
          value={search}
        />
      </label>

      <label className="shopifyFilterField">
        <span>Valor mínimo</span>
        <input
          className="shopifyTextInput"
          inputMode="decimal"
          onChange={(event) => onMinTotalSpentChange(event.target.value)}
          placeholder="0"
          type="number"
          value={minTotalSpent}
        />
      </label>

      <label className="shopifyFilterField">
        <span>Valor máximo</span>
        <input
          className="shopifyTextInput"
          inputMode="decimal"
          onChange={(event) => onMaxTotalSpentChange(event.target.value)}
          placeholder="Sem limite"
          type="number"
          value={maxTotalSpent}
        />
      </label>

      <label className="shopifyFilterField">
        <span>Pedidos mínimos</span>
        <input
          className="shopifyTextInput"
          inputMode="numeric"
          min="1"
          onChange={(event) => onMinOrdersChange(event.target.value)}
          placeholder="1"
          type="number"
          value={minOrders}
        />
      </label>

      <label className="shopifyFilterField">
        <span>Status</span>
        <select
          className="select"
          onChange={(event) => onLifecycleChange(event.target.value as LifecycleFilter)}
          value={lifecycle}
        >
          <option value="all">Todos</option>
          <option value="new">Novos</option>
          <option value="recurring">Recorrentes</option>
        </select>
      </label>

      <label className="shopifyFilterField">
        <span>Ordenar por</span>
        <select
          className="select"
          onChange={(event) => onSortByChange(event.target.value as SortBy)}
          value={sortBy}
        >
          <option value="total_spent">Maior valor comprado</option>
          <option value="total_orders">Maior número de pedidos</option>
          <option value="last_purchase_at">Compra mais recente</option>
        </select>
      </label>
    </div>
  );
}
