import { Routes } from '@angular/router';
import { BwpLicenseComponent } from './pages/bwp-license/bwp-license.component';
import { ChampionshipStandingsComponent } from './pages/championship-standings/championship-standings.component';
import { RaceResultsComponent } from './pages/race-results/race-results.component';
import { SkfHistoryComponent } from './pages/skf-history/skf-history.component';

export const appRoutes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'bwp-license' },
  { path: 'bwp-license', component: BwpLicenseComponent },
  { path: 'standings', pathMatch: 'full', redirectTo: 'championship-standings' },
  { path: 'championship-standings', component: ChampionshipStandingsComponent },
  { path: 'skf-history', component: SkfHistoryComponent },
  { path: 'race-results', component: RaceResultsComponent },
  { path: '**', redirectTo: 'bwp-license' }
];
