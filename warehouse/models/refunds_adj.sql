select
    o.order_id,
    e.event_id,
    case when e.event_type = 'refund' then -o.gross_amount else 0 end as adjustment_amount
from {{ ref('orders_replica') }} o
join {{ ref('events_raw') }} e on e.order_id = o.order_id
