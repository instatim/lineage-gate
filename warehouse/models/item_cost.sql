select
    oi.order_item_id,
    oi.order_id,
    oi.sku,
    oi.qty,
    rf.retailer_cost,
    oi.qty * rf.retailer_cost as extended_cost,
    mf.score as ml_score
from {{ ref('order_items') }} oi
join {{ ref('retailer_feed') }} rf on rf.sku = oi.sku
left join {{ ref('ml_features') }} mf on mf.order_id = oi.order_id
