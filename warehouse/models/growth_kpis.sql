select
    metric_source,
    sum(n) as total
from {{ ref('growth_metrics') }}
group by metric_source
