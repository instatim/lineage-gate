select
    order_id,
    sum(adjustment_amount) as adjustments
from {{ ref('refunds_adj') }}
group by order_id
