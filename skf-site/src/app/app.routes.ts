import { Routes } from '@angular/router';
import { adminGuard } from './guards/admin.guard';
import { AdminUsersComponent } from './pages/admin-users/admin-users.component';
import { BwpLicenseComponent } from './pages/bwp-license/bwp-license.component';
import { HomeVisitComponent } from './pages/home-visit/home-visit.component';
import { ChampionshipStandingsComponent } from './pages/championship-standings/championship-standings.component';
import { ProfileComponent } from './pages/profile/profile.component';
import { RaceResultsComponent } from './pages/race-results/race-results.component';
import { SkfHistoryComponent } from './pages/skf-history/skf-history.component';

export const appRoutes: Routes = [
  { path: '', component: HomeVisitComponent },
  { path: 'home', component: HomeVisitComponent },
  { path: 'bwp-license', component: BwpLicenseComponent },
  { path: 'standings', pathMatch: 'full', redirectTo: 'championship-standings' },
  { path: 'championship-standings', component: ChampionshipStandingsComponent },
  { path: 'skf-history', component: SkfHistoryComponent },
  { path: 'race-results', component: RaceResultsComponent },
  { path: 'profile', component: ProfileComponent },
  { path: 'admin/users', component: AdminUsersComponent, canActivate: [adminGuard] },
  { path: '**', redirectTo: '' }
];
