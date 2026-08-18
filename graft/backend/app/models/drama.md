# backend/app/models/drama.py · [[orm-model-registry]]

- gen_drama_code · function · L33-L38 — Generates the operator-readable unique drama ID as DR-<8 uppercase hex chars> from uuid4 for the code column.
- Drama · class · L41-L93 — Main drama table where name is the dedup key (re-importing same name updates the row) and code is the operator-readable unique ID, with dual uniqueness.
- __repr__ · method · L92-L93 — Debug-friendly string representation of a Drama instance showing id, code, and name.
- DramaStill · class · L96-L108 — One-to-many drama stills table storing MinIO object keys with sortable ordering, cascade-deleted with the parent drama.
- __repr__ · method · L107-L108 — Debug-friendly string representation of a DramaStill instance showing id and file_key.
- DramaAccount · class · L111-L129 — Many-to-many join table linking dramas to video accounts, enforcing a unique (drama_id, account_id) pair so one drama can be listed on multiple accounts without duplicates.
- DramaMaterial · class · L132-L144 — Records the independent drama-to-publish-material correspondence (optionally per account) so the drama library can aggregate generated publish materials.
