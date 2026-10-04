-- The shop and the logins to keep, as keep.json for scripts.demo_data.
-- Demo staff from an earlier load (phones 90000200xx) are not kept: they are
-- made again with the new data.
SELECT json_build_object(
  'shop_id', s.id,
  'users', json_agg(json_build_object('id', u.id, 'name', u.name, 'role', u.role)
                    ORDER BY (u.role = 'owner') DESC, u.created_at))
FROM shops s JOIN users u ON u.shop_id = s.id
WHERE u.phone NOT LIKE '90000200__'
GROUP BY s.id;
