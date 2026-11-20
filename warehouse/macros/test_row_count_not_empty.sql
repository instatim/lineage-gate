{% test row_count_not_empty(model) %}
with counts as (
    select count(*) as row_count from {{ model }}
)
select * from counts where row_count = 0
{% endtest %}
