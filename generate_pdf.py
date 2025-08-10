import os
from reportlab.lib.pagesizes import letter, A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER, TA_LEFT
from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Image
import datetime

def create_pdf():
    # PDFファイル名
    pdf_file = "repograph_integration_plan.pdf"
    
    # PDFドキュメントの作成
    doc = SimpleDocTemplate(
        pdf_file,
        pagesize=A4,
        rightMargin=72,
        leftMargin=72,
        topMargin=72,
        bottomMargin=18,
    )
    
    # スタイルの取得
    styles = getSampleStyleSheet()
    
    # カスタムスタイルの作成
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#1a472a'),
        spaceAfter=30,
        alignment=TA_CENTER
    )
    
    heading1_style = ParagraphStyle(
        'CustomHeading1',
        parent=styles['Heading1'],
        fontSize=18,
        textColor=colors.HexColor('#2c5282'),
        spaceAfter=12,
        spaceBefore=12
    )
    
    heading2_style = ParagraphStyle(
        'CustomHeading2',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#2d3748'),
        spaceAfter=6,
        spaceBefore=12
    )
    
    body_style = ParagraphStyle(
        'CustomBody',
        parent=styles['BodyText'],
        fontSize=11,
        alignment=TA_JUSTIFY,
        spaceAfter=12
    )
    
    code_style = ParagraphStyle(
        'Code',
        parent=styles['Code'],
        fontSize=9,
        leftIndent=20,
        rightIndent=20,
        backColor=colors.HexColor('#f7fafc'),
        borderColor=colors.HexColor('#cbd5e0'),
        borderWidth=1,
        borderPadding=10,
        spaceAfter=12
    )
    
    # コンテンツリスト
    content = []
    
    # タイトルページ
    content.append(Paragraph("Repograph-PatchPilot", title_style))
    content.append(Paragraph("統合計画書", title_style))
    content.append(Spacer(1, 0.5*inch))
    content.append(Paragraph(f"作成日: {datetime.datetime.now().strftime('%Y年%m月%d日')}", styles['Normal']))
    content.append(PageBreak())
    
    # 1. エグゼクティブサマリー
    content.append(Paragraph("1. エグゼクティブサマリー", heading1_style))
    content.append(Paragraph(
        "本計画書は、RepographをPatchPilotのlocalizationステップに統合し、"
        "障害位置特定の精度を向上させるための実装計画を示します。",
        body_style
    ))
    content.append(Spacer(1, 0.2*inch))
    
    content.append(Paragraph("目標", heading2_style))
    content.append(Paragraph(
        "• <b>主要目標</b>: コードグラフベースの依存関係解析により、より正確な障害位置特定を実現<br/>"
        "• <b>期待効果</b>: 障害位置特定の精度向上、関連コードの見逃し削減、修正成功率の向上",
        body_style
    ))
    content.append(Spacer(1, 0.3*inch))
    
    # 2. 技術的アーキテクチャ
    content.append(Paragraph("2. 技術的アーキテクチャ", heading1_style))
    
    content.append(Paragraph("2.1 現在のPatchPilotアーキテクチャ", heading2_style))
    content.append(Paragraph(
        "問題文 → Localization(FL) → Repair → Validation → Refinement",
        code_style
    ))
    
    content.append(Paragraph("2.2 統合後のアーキテクチャ", heading2_style))
    content.append(Paragraph(
        "問題文 → [コードグラフ構築] → Localization(FL+Graph) → Repair → Validation<br/>"
        "　　　　　　↑ Repograph 　　　　　　↑ 依存関係を考慮",
        code_style
    ))
    content.append(Spacer(1, 0.3*inch))
    
    # 3. 実装計画
    content.append(Paragraph("3. 実装計画", heading1_style))
    
    content.append(Paragraph("Phase 1: 基盤整備（1週目）", heading2_style))
    content.append(Paragraph(
        "• 依存関係の追加 (networkx, tree-sitter-languages, pygments)<br/>"
        "• Repographモジュールの移植<br/>"
        "• patchpilot/graph/ディレクトリの作成",
        body_style
    ))
    
    content.append(Paragraph("Phase 2: Localizationモジュールの拡張（2週目）", heading2_style))
    content.append(Paragraph(
        "• LLMFLWithGraphクラスの実装<br/>"
        "• グラフ構築・検索機能の統合<br/>"
        "• コンテキスト生成機能の追加",
        body_style
    ))
    
    content.append(Paragraph("Phase 3: CLIインターフェース（3週目）", heading2_style))
    content.append(Paragraph(
        "• コマンドライン引数の追加 (--repo_graph, --graph_depth)<br/>"
        "• 実行スクリプトの作成<br/>"
        "• キャッシュ機能の実装",
        body_style
    ))
    
    content.append(Paragraph("Phase 4: テストと評価（4週目）", heading2_style))
    content.append(Paragraph(
        "• ユニットテストの作成<br/>"
        "• SWE-bench-liteでのベンチマーク評価<br/>"
        "• パフォーマンス測定",
        body_style
    ))
    content.append(PageBreak())
    
    # 4. 実装の優先順位
    content.append(Paragraph("4. 実装の優先順位", heading1_style))
    
    # テーブルデータ
    priority_data = [
        ['優先度', 'タスク', '理由'],
        ['高', 'グラフ構築機能', 'コア機能として必須'],
        ['高', 'Localization統合', '主要目標の実現に必要'],
        ['高', 'キャッシュ機能', '大規模リポジトリ対応'],
        ['中', 'グラフ探索最適化', 'パフォーマンス向上'],
        ['中', 'プロンプト改良', '精度向上'],
        ['低', '可視化機能', '追加機能'],
    ]
    
    # テーブルの作成
    table = Table(priority_data, colWidths=[1.5*inch, 2.5*inch, 2.5*inch])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 12),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    content.append(table)
    content.append(Spacer(1, 0.3*inch))
    
    # 5. リスクと対策
    content.append(Paragraph("5. リスクと対策", heading1_style))
    
    risk_data = [
        ['リスク', '影響度', '対策'],
        ['グラフ構築の計算コスト', '高', 'キャッシュ機能、事前計算'],
        ['メモリ使用量', '中', '段階的構築、不要ノード削除'],
        ['既存機能への影響', '低', 'フラグによる切り替え'],
    ]
    
    risk_table = Table(risk_data, colWidths=[2.5*inch, 1*inch, 3*inch])
    risk_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#dc2626')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    content.append(risk_table)
    content.append(Spacer(1, 0.3*inch))
    
    # 6. 成功指標
    content.append(Paragraph("6. 成功指標", heading1_style))
    content.append(Paragraph(
        "<b>技術指標:</b><br/>"
        "• 障害位置特定の精度が10%以上向上<br/>"
        "• False Positive率が20%以上削減<br/><br/>"
        "<b>パフォーマンス指標:</b><br/>"
        "• グラフ構築時間: 中規模リポジトリで60秒以内<br/>"
        "• メモリ使用量: 2GB以内",
        body_style
    ))
    content.append(PageBreak())
    
    # 7. タイムライン
    content.append(Paragraph("7. タイムライン", heading1_style))
    
    timeline_data = [
        ['週', 'フェーズ', '主要成果物'],
        ['Week 1', '基盤整備', '依存関係追加、モジュール移植'],
        ['Week 2', 'Localization拡張', 'グラフ統合機能'],
        ['Week 3', 'CLI/スクリプト', '実行環境整備'],
        ['Week 4', 'テスト・評価', 'ベンチマーク結果、ドキュメント'],
    ]
    
    timeline_table = Table(timeline_data, colWidths=[1.5*inch, 2*inch, 3*inch])
    timeline_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e40af')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 11),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#dbeafe')),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
    ]))
    content.append(timeline_table)
    content.append(Spacer(1, 0.3*inch))
    
    # 8. 次のステップ
    content.append(Paragraph("8. 次のステップ", heading1_style))
    content.append(Paragraph(
        "1. 本計画書の承認<br/>"
        "2. 開発環境のセットアップ<br/>"
        "3. Phase 1の実装開始<br/>"
        "4. 週次進捗レビュー",
        body_style
    ))
    
    # PDFの生成
    doc.build(content)
    return pdf_file

if __name__ == "__main__":
    pdf_file = create_pdf()
    print(f"PDF file generated: {pdf_file}")