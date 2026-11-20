select
    order_id,
    sum(extended_cost) as cogs
from {{ ref('item_cost') }}
group by order_id
