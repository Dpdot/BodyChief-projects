/* =========================================================
   Tabela kalendarza (DimDate) z polskimi świętami
   SQL Server 2016+ (ISO_WEEK, DATEFROMPARTS, CHOOSE)
   ========================================================= */

-- 1) Funkcja licząca datę Wielkanocy (algorytm Meeusa/Jonesa/Butchera)
CREATE OR ALTER FUNCTION dbo.fn_EasterSunday (@Year INT)
RETURNS DATE
WITH SCHEMABINDING
AS
BEGIN
    DECLARE @a INT = @Year % 19,
            @b INT = @Year / 100,
            @c INT = @Year % 100;
    DECLARE @d INT = @b / 4,
            @e INT = @b % 4,
            @f INT = (@b + 8) / 25;
    DECLARE @g INT = (@b - @f + 1) / 3;
    DECLARE @h INT = (19 * @a + @b - @d - @g + 15) % 30,
            @i INT = @c / 4,
            @k INT = @c % 4;
    DECLARE @l INT = (32 + 2 * @e + 2 * @i - @h - @k) % 7;
    DECLARE @m INT = (@a + 11 * @h + 22 * @l) / 451;

    RETURN DATEFROMPARTS(
        @Year,
        (@h + @l - 7 * @m + 114) / 31,
        ((@h + @l - 7 * @m + 114) % 31) + 1);
END;
GO

-- 2) Tabela
DROP TABLE IF EXISTS dbo.DimDate;

CREATE TABLE dbo.DimDate (
    DateKey      INT           NOT NULL PRIMARY KEY,   -- yyyymmdd, np. 20261016
    [Date]       DATE          NOT NULL UNIQUE,
    [Year]       SMALLINT      NOT NULL,
    [Quarter]    TINYINT       NOT NULL,
    [Month]      TINYINT       NOT NULL,
    MonthName    NVARCHAR(20)  NOT NULL,
    IsoWeek      TINYINT       NOT NULL,               -- numer tygodnia ISO (PL)
    IsoYear      SMALLINT      NOT NULL,               -- rok, do którego należy tydzień ISO
    [Day]        TINYINT       NOT NULL,
    DayOfYear    SMALLINT      NOT NULL,
    DayOfWeek    TINYINT       NOT NULL,               -- 1 = poniedziałek ... 7 = niedziela
    DayName      NVARCHAR(20)  NOT NULL,
    IsWeekend    BIT           NOT NULL,
    IsHoliday    BIT           NOT NULL DEFAULT 0,
    HolidayName  NVARCHAR(60)  NULL,
    IsWorkday    AS CAST(CASE WHEN IsWeekend = 0 AND IsHoliday = 0 THEN 1 ELSE 0 END AS BIT) PERSISTED
);
GO

-- 3) Wypełnienie zakresu dat
DECLARE @Start DATE = '2000-01-01',
        @End   DATE = '2050-12-31';

WITH N AS (
    SELECT TOP (DATEDIFF(DAY, @Start, @End) + 1)
           ROW_NUMBER() OVER (ORDER BY (SELECT NULL)) - 1 AS n
    FROM sys.all_objects a
    CROSS JOIN sys.all_objects b
)
INSERT INTO dbo.DimDate
    (DateKey, [Date], [Year], [Quarter], [Month], MonthName, IsoWeek, IsoYear,
     [Day], DayOfYear, DayOfWeek, DayName, IsWeekend)
SELECT
    CONVERT(INT, CONVERT(CHAR(8), x.d, 112)),
    x.d,
    YEAR(x.d),
    DATEPART(QUARTER, x.d),
    MONTH(x.d),
    CHOOSE(MONTH(x.d), N'styczeń', N'luty', N'marzec', N'kwiecień', N'maj', N'czerwiec',
                       N'lipiec', N'sierpień', N'wrzesień', N'październik', N'listopad', N'grudzień'),
    DATEPART(ISO_WEEK, x.d),
    YEAR(DATEADD(DAY, 26 - DATEPART(ISO_WEEK, x.d), x.d)),
    DAY(x.d),
    DATEPART(DAYOFYEAR, x.d),
    w.dow,
    CHOOSE(w.dow, N'poniedziałek', N'wtorek', N'środa', N'czwartek', N'piątek', N'sobota', N'niedziela'),
    CASE WHEN w.dow IN (6, 7) THEN 1 ELSE 0 END
FROM N
CROSS APPLY (SELECT DATEADD(DAY, N.n, @Start) AS d) x
-- numer dnia tygodnia niezależny od ustawienia DATEFIRST (1900-01-01 to poniedziałek)
CROSS APPLY (SELECT DATEDIFF(DAY, '19000101', x.d) % 7 + 1 AS dow) w;
GO

-- 4) Święta ustawowo wolne od pracy w Polsce
WITH Years AS (
    SELECT DISTINCT [Year] FROM dbo.DimDate
),
Holidays AS (
    SELECT v.d, v.n
    FROM Years y
    CROSS APPLY (SELECT dbo.fn_EasterSunday(y.[Year]) AS E) e
    CROSS APPLY (VALUES
        (DATEFROMPARTS(y.[Year], 1, 1),   N'Nowy Rok'),
        (DATEFROMPARTS(y.[Year], 1, 6),   N'Święto Trzech Króli'),
        (e.E,                             N'Wielkanoc'),
        (DATEADD(DAY, 1, e.E),            N'Poniedziałek Wielkanocny'),
        (DATEFROMPARTS(y.[Year], 5, 1),   N'Święto Pracy'),
        (DATEFROMPARTS(y.[Year], 5, 3),   N'Święto Konstytucji 3 Maja'),
        (DATEADD(DAY, 49, e.E),           N'Zielone Świątki'),
        (DATEADD(DAY, 60, e.E),           N'Boże Ciało'),
        (DATEFROMPARTS(y.[Year], 8, 15),  N'Wniebowzięcie NMP'),
        (DATEFROMPARTS(y.[Year], 11, 1),  N'Wszystkich Świętych'),
        (DATEFROMPARTS(y.[Year], 11, 11), N'Narodowe Święto Niepodległości'),
        (CASE WHEN y.[Year] >= 2025 THEN DATEFROMPARTS(y.[Year], 12, 24) END, N'Wigilia'),
        (DATEFROMPARTS(y.[Year], 12, 25), N'Boże Narodzenie (1. dzień)'),
        (DATEFROMPARTS(y.[Year], 12, 26), N'Boże Narodzenie (2. dzień)')
        -- Trzech Króli jest wolne od 2011 r.; dla wcześniejszych lat dodaj warunek jak przy Wigilii
    ) v(d, n)
    WHERE v.d IS NOT NULL
)
UPDATE dd
SET IsHoliday   = 1,
    HolidayName = h.n
FROM dbo.DimDate dd
JOIN Holidays h ON h.d = dd.[Date];
GO

-- Test
SELECT * FROM dbo.DimDate WHERE [Year] = 2026 AND IsHoliday = 1 ORDER BY [Date];
