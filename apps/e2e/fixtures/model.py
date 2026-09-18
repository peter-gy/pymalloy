SALES = "region,amount\nNorth,40\nNorth,2\nSouth,30\n"
UPDATED_SALES = "region,amount\nNorth,70\nSouth,10\n"
SOURCE = """
##! experimental.givens
 given: region_filter :: string is 'North'
 source: sales is duckdb.table('sales.csv') extend {
   measure: revenue is amount.sum()
   view: by_region is {
     group_by: region
     aggregate: revenue
     order_by: region
   }
   view: detail is {
     group_by: region
     nest: values is {group_by: amount aggregate: subtotal is amount.sum() order_by: amount}
     order_by: region
   }
   view: filtered is {
     where: region = $region_filter
     aggregate: revenue
   }
 }
"""
