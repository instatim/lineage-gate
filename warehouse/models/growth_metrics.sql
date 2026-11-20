select 'experiments' as metric_source, count(*) as n from {{ ref('experiments') }}
union all
select 'ml_features' as metric_source, count(*) as n from {{ ref('ml_features') }}
