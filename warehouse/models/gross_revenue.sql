select
    order_id,
    sum(paid_amount) as gross_revenue,
    sum(fee_amount) as fees
from {{ ref('order_fees') }}
group by order_id
