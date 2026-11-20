select
    o.order_id,
    p.payment_id,
    o.gross_amount,
    p.amount as paid_amount,
    greatest(o.gross_amount - p.amount, 0) as fee_amount
from {{ ref('orders_replica') }} o
join {{ ref('payments') }} p on p.order_id = o.order_id
