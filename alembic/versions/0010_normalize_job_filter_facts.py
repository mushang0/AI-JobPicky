"""normalize persisted job filter facts conservatively

Revision ID: 0010_normalize_job_filter_facts
Revises: 0009_job_pool_and_saved_jobs
Create Date: 2026-08-01

Only confirmed aliases are mapped. Unrecognized scalar facts become NULL,
unrecognized city names remain usable display values, and every changed row
keeps its original filter facts in metadata. The downgrade intentionally does
not restore old values because later ingestion may have superseded them.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010_normalize_job_filter_facts"
down_revision: str | None = "0009_job_pool_and_saved_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        r"""
        WITH prepared AS (
            SELECT
                id,
                company_nature AS old_company_nature,
                recruitment_type AS old_recruitment_type,
                education_requirement AS old_education,
                locations AS old_locations,
                regexp_replace(
                    btrim(coalesce(company_nature, '')),
                    '\s+',
                    '',
                    'g'
                ) AS company_key,
                regexp_replace(
                    btrim(coalesce(recruitment_type, '')),
                    '\s+',
                    '',
                    'g'
                ) AS recruitment_key,
                replace(
                    replace(
                        regexp_replace(
                            btrim(coalesce(education_requirement, '')),
                            '\s+',
                            '',
                            'g'
                        ),
                        '博士研究生',
                        '博士'
                    ),
                    '硕士研究生',
                    '硕士'
                ) AS education_key
            FROM job
        ),
        scalar_facts AS (
            SELECT
                prepared.*,
                CASE company_key
                    WHEN '央企' THEN '央企'
                    WHEN '中央企业' THEN '央企'
                    WHEN '中央国有企业' THEN '央企'
                    WHEN '国企' THEN '国企'
                    WHEN '国有企业' THEN '国企'
                    WHEN '地方国企' THEN '国企'
                    WHEN '地方国有企业' THEN '国企'
                    WHEN '事业单位' THEN '事业单位'
                    WHEN '政府/公共机构' THEN '政府/公共机构'
                    WHEN '政府公共机构' THEN '政府/公共机构'
                    WHEN '政府机构' THEN '政府/公共机构'
                    WHEN '公共机构' THEN '政府/公共机构'
                    WHEN '民营企业' THEN '民营企业'
                    WHEN '民营' THEN '民营企业'
                    WHEN '民企' THEN '民营企业'
                    WHEN '私企' THEN '民营企业'
                    WHEN '私营企业' THEN '民营企业'
                    WHEN '外资企业' THEN '外资企业'
                    WHEN '外企' THEN '外资企业'
                    WHEN '外商独资' THEN '外资企业'
                    WHEN '外商独资企业' THEN '外资企业'
                    WHEN '合资企业' THEN '合资企业'
                    WHEN '合资' THEN '合资企业'
                    WHEN '其他' THEN '其他'
                    WHEN '其它' THEN '其他'
                    ELSE NULL
                END AS new_company_nature,
                recruitment_key ~ '(校招|校园|应届|春招|秋招|提前批|补招)'
                    AS is_campus,
                recruitment_key ~ '(社招|社会招聘)' AS is_social,
                recruitment_key LIKE '%实习%' AS is_internship,
                CASE
                    WHEN education_key IN (
                        '', '-', '--', '/', '不详', '未知', '待定',
                        '不限', '无要求', '不要求'
                    )
                        OR education_key LIKE '%学历不限%'
                        OR education_key LIKE '%不限学历%'
                        OR education_key LIKE '%学历无要求%'
                        OR education_key LIKE '%无学历要求%'
                        OR education_key LIKE '%学历不要求%'
                        THEN NULL
                    WHEN education_key ~ '(高中|中专|中职|技校|初中|小学)'
                        THEN '高中及以下'
                    WHEN education_key ~ '(专科|大专)' THEN '专科'
                    WHEN education_key ~ '(本科|学士)' THEN '本科'
                    WHEN education_key LIKE '%硕士%' THEN '硕士'
                    WHEN education_key LIKE '%博士%' THEN '博士'
                    ELSE NULL
                END AS new_education
            FROM prepared
        ),
        split_locations AS (
            SELECT
                prepared.id,
                source_location.array_ordinality,
                split_location.part_ordinality,
                split_location.raw_location,
                regexp_replace(
                    btrim(split_location.raw_location),
                    '\s+',
                    '',
                    'g'
                ) AS location_key
            FROM prepared
            CROSS JOIN LATERAL unnest(prepared.old_locations)
                WITH ORDINALITY AS source_location(raw_location, array_ordinality)
            CROSS JOIN LATERAL regexp_split_to_table(
                source_location.raw_location,
                '[,，、;/；|]+'
            ) WITH ORDINALITY AS split_location(raw_location, part_ordinality)
        ),
        location_values AS (
            SELECT
                id,
                array_ordinality,
                part_ordinality,
                CASE
                    WHEN location_key IN (
                        '', '-', '--', '/', '不详', '未知', '待定',
                        '不限', '城市不限', '地点不限', '工作地点不限'
                    ) THEN NULL
                    WHEN lower(location_key) IN ('remote', 'workfromhome')
                        OR location_key IN (
                            '线上', '在线', '居家办公', '远程', '远程办公'
                        ) THEN '远程'
                    WHEN location_key IN ('全国', '全国各地', '全国多地', '全国范围')
                        THEN '全国'
                    WHEN char_length(location_key) > 1
                        AND right(location_key, 1) = '市'
                        THEN left(location_key, char_length(location_key) - 1)
                    ELSE regexp_replace(btrim(raw_location), '\s+', ' ', 'g')
                END AS city
            FROM split_locations
        ),
        ranked_locations AS (
            SELECT
                id,
                city,
                array_ordinality,
                part_ordinality,
                row_number() OVER (
                    PARTITION BY id, city
                    ORDER BY array_ordinality, part_ordinality
                ) AS city_rank
            FROM location_values
            WHERE city IS NOT NULL AND city <> ''
        ),
        location_arrays AS (
            SELECT
                id,
                array_agg(city ORDER BY array_ordinality, part_ordinality)
                    FILTER (WHERE city_rank = 1) AS new_locations
            FROM ranked_locations
            GROUP BY id
        ),
        normalized AS (
            SELECT
                scalar_facts.*,
                CASE
                    WHEN (
                        is_campus::integer
                        + is_social::integer
                        + is_internship::integer
                    ) <> 1 THEN NULL
                    WHEN is_campus THEN '校招'
                    WHEN is_social THEN '社招'
                    ELSE '实习'
                END AS new_recruitment_type,
                coalesce(location_arrays.new_locations, ARRAY[]::text[])
                    AS new_locations
            FROM scalar_facts
            LEFT JOIN location_arrays USING (id)
        ),
        changed AS (
            SELECT *
            FROM normalized
            WHERE old_company_nature IS DISTINCT FROM new_company_nature
                OR old_recruitment_type IS DISTINCT FROM new_recruitment_type
                OR old_education IS DISTINCT FROM new_education
                OR old_locations IS DISTINCT FROM new_locations
        )
        UPDATE job
        SET
            company_nature = changed.new_company_nature,
            recruitment_type = changed.new_recruitment_type,
            education_requirement = changed.new_education,
            locations = changed.new_locations,
            metadata = CASE
                WHEN coalesce(job.metadata, '{}'::jsonb)
                    ? '_normalization_v1_original'
                    THEN coalesce(job.metadata, '{}'::jsonb)
                ELSE jsonb_set(
                    coalesce(job.metadata, '{}'::jsonb),
                    '{_normalization_v1_original}',
                    jsonb_build_object(
                        'company_nature', job.company_nature,
                        'recruitment_type', job.recruitment_type,
                        'education_requirement', job.education_requirement,
                        'locations', job.locations
                    ),
                    true
                )
            END,
            embedding = NULL,
            content_hash = NULL,
            fact_version = 'norm-v1-' || md5(
                jsonb_build_object(
                    'previous_fact_version', job.fact_version,
                    'company_nature', changed.new_company_nature,
                    'recruitment_type', changed.new_recruitment_type,
                    'education_requirement', changed.new_education,
                    'locations', changed.new_locations
                )::text
            ),
            updated_at = CURRENT_TIMESTAMP
        FROM changed
        WHERE job.id = changed.id
        """
    )

    op.create_check_constraint(
        "ck_job_company_nature_normalized",
        "job",
        "company_nature IS NULL OR company_nature IN ("
        "'央企', '国企', '事业单位', '政府/公共机构', "
        "'民营企业', '外资企业', '合资企业', '其他')",
    )
    op.create_check_constraint(
        "ck_job_recruitment_type_normalized",
        "job",
        "recruitment_type IS NULL OR recruitment_type IN ('校招', '社招', '实习')",
    )
    op.create_check_constraint(
        "ck_job_education_requirement_normalized",
        "job",
        "education_requirement IS NULL OR education_requirement IN ("
        "'高中及以下', '专科', '本科', '硕士', '博士')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_job_education_requirement_normalized",
        "job",
        type_="check",
    )
    op.drop_constraint(
        "ck_job_recruitment_type_normalized",
        "job",
        type_="check",
    )
    op.drop_constraint(
        "ck_job_company_nature_normalized",
        "job",
        type_="check",
    )
